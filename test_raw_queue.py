import json
from pathlib import Path
import tempfile
import unittest
from raw_queue import RawQueue


class RawQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.files=[self.root/name for name in ('кадр один.ARW','second.ARW','third.ARW')]
        for p in self.files:p.write_bytes(b'raw')
        self.q=RawQueue(self.root)

    def test_multi_add_deduplicates_and_does_not_change_current(self):
        rows=self.q.add(self.files[:2],{'sony_profile':'sony:8'})
        first=self.q.current
        self.q.add([self.files[1],self.files[2]])
        self.assertEqual(len(self.q.items),3)
        self.assertEqual(self.q.current,first)
        self.assertEqual(self.q.next()['source'],str(self.files[1]))
        self.assertEqual(rows[0]['settings']['sony_profile'],'sony:8')

    def test_selection_and_order_survive_restart(self):
        rows=self.q.add(self.files)
        self.q.move(rows[2]['id'],-1)
        self.q.select(rows[2]['id'])
        restored=RawQueue(self.root)
        self.assertEqual(restored.current,rows[2]['id'])
        self.assertEqual(restored.next()['id'],rows[1]['id'])

    def test_remove_does_not_delete_raw_and_current_is_protected(self):
        rows=self.q.add(self.files)
        with self.assertRaises(ValueError):self.q.remove(rows[0]['id'])
        self.q.remove(rows[1]['id'])
        self.assertTrue(self.files[1].exists())
        self.assertEqual(len(self.q.items),2)

    def test_interrupted_work_requires_revalidation(self):
        row=self.q.add([self.files[0]])[0];row['status']='running';self.q.save()
        self.assertEqual(RawQueue(self.root).selected()['status'],'waiting')

    def test_invalid_inputs_and_broken_persistence(self):
        path=self.root/'photo.jpg';path.write_bytes(b'not raw')
        with self.assertRaises(ValueError):self.q.add([path])
        self.q.path.write_text('{broken')
        self.assertEqual(RawQueue(self.root).items,[])


if __name__=='__main__':unittest.main()
