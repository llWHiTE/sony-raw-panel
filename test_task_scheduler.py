import unittest
from task_scheduler import Scheduler


class SchedulerTests(unittest.TestCase):
    def test_manual_tasks_precede_speculation_and_scan(self):
        q=Scheduler()
        q.put(('scan',lambda:None))
        q.put(('next',lambda:None),priority=20)
        q.put(('full',lambda:None),priority=10)
        q.put(('apply',lambda:None))
        self.assertEqual([q.get()[0] for _ in range(4)],['apply','full','next','scan'])

    def test_same_priority_keeps_order(self):
        q=Scheduler()
        for i in range(3):q.put((str(i),lambda:None))
        self.assertEqual([q.get()[0] for _ in range(3)],['0','1','2'])

    def test_replacing_waiting_task_does_not_replay_old_choice(self):
        q=Scheduler()
        old=q.put(('profile-a',lambda:None),key='profile',generation=1)
        q.put(('profile-b',lambda:None),key='profile',generation=2)
        self.assertTrue(old.cancelled)
        self.assertEqual(q.get()[0],'profile-b')

    def test_cancel_does_not_interrupt_active_native_command(self):
        q=Scheduler();task=q.put(('export',lambda:None),key='export')
        q.get();q.cancel('export')
        self.assertFalse(task.cancelled)

    def test_stop_discards_waiting_work(self):
        q=Scheduler();q.put(('next',lambda:None));q.put(None)
        self.assertIsNone(q.get())


if __name__=='__main__':unittest.main()
