using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Threading;
using System.Windows.Forms;

[assembly: AssemblyTitle("Sony RAW Panel")]
[assembly: AssemblyDescription("Portable Sony Imaging Edge to Photoshop workflow panel")]
[assembly: AssemblyCompany("Alexey Storozhilov")]
[assembly: AssemblyProduct("Sony RAW Panel")]
[assembly: AssemblyCopyright("Copyright © 2026 Alexey Storozhilov")]
[assembly: AssemblyVersion("0.6.0.0")]
[assembly: AssemblyFileVersion("0.6.0.0")]

internal static class PortableLauncher
{
    private static string Quote(string value)
    {
        if (value.IndexOf('"') >= 0) throw new ArgumentException("Invalid quote in argument.");
        return "\"" + value + "\"";
    }

    private static string PayloadHash(Stream input)
    {
        using (var sha = SHA256.Create())
            return BitConverter.ToString(sha.ComputeHash(input)).Replace("-", "").Substring(0, 16).ToLowerInvariant();
    }

    [STAThread]
    private static int Main(string[] args)
    {
        try
        {
            string home = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
            string data = Path.Combine(home, "data");
            Directory.CreateDirectory(data);
            string stamp;
            using (Stream payload = Assembly.GetExecutingAssembly().GetManifestResourceStream("SonyRawPayload"))
                stamp = PayloadHash(payload);
            string runtime = Path.Combine(data, "runtime-0.6.0-" + stamp);
            bool created;
            using (var mutex = new Mutex(false, "Local\\SonyRawExtract-" + stamp, out created))
            {
                bool acquired;
                try { acquired = mutex.WaitOne(TimeSpan.FromMinutes(2)); }
                catch (AbandonedMutexException) { acquired = true; }
                if (!acquired) throw new IOException("Another copy is preparing its runtime. Retry shortly.");
                try
                {
                    string marker = Path.Combine(runtime, ".complete");
                    if (!File.Exists(marker))
                    {
                        Directory.CreateDirectory(runtime);
                        using (Stream payload = Assembly.GetExecutingAssembly().GetManifestResourceStream("SonyRawPayload"))
                        using (var archive = new ZipArchive(payload, ZipArchiveMode.Read))
                        {
                            foreach (ZipArchiveEntry entry in archive.Entries)
                            {
                                string target = Path.GetFullPath(Path.Combine(runtime, entry.FullName));
                                if (!target.StartsWith(Path.GetFullPath(runtime) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
                                    throw new IOException("Unexpected runtime entry.");
                                if (String.IsNullOrEmpty(entry.Name)) { Directory.CreateDirectory(target); continue; }
                                Directory.CreateDirectory(Path.GetDirectoryName(target));
                                using (Stream source = entry.Open())
                                using (Stream output = new FileStream(target, FileMode.Create, FileAccess.Write, FileShare.None))
                                    source.CopyTo(output);
                            }
                        }
                        File.WriteAllText(marker, stamp);
                    }
                }
                finally { mutex.ReleaseMutex(); }
            }
            var start = new ProcessStartInfo();
            start.FileName = Path.Combine(runtime, "pythonw.exe");
            start.Arguments = "-I " + Quote(Path.Combine(runtime, "app", "sony_panel.py"));
            foreach (string arg in args) start.Arguments += " " + Quote(arg);
            start.WorkingDirectory = home;
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            start.EnvironmentVariables["SONY_RAW_PORTABLE_HOME"] = home;
            start.EnvironmentVariables["TCL_LIBRARY"] = Path.Combine(runtime, "tcl", "tcl8.6");
            start.EnvironmentVariables["TK_LIBRARY"] = Path.Combine(runtime, "tcl", "tk8.6");
            using (Process child = Process.Start(start))
            {
                child.WaitForExit();
                return child.ExitCode;
            }
        }
        catch (Exception error)
        {
            MessageBox.Show("Sony RAW Panel could not start.\nPlace the EXE in a writable folder.\n\n" + error.Message,
                            "Sony RAW Panel", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
