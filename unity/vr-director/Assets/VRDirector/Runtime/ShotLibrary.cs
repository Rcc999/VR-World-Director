using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace VRDirector
{
    /// <summary>
    /// The shots made in the current scene, like takes on a film set:
    /// &lt;persistentDataPath&gt;/Shots/&lt;scene&gt;/&lt;yyyyMMdd_HHmmss&gt;/ holds
    /// frame_*.png and shot.json (name, number, camera keyframes, every frame's pose).
    /// Numbers count every shot ever made in the scene (shot1, shot2...), so deleting
    /// one never reuses its number. Names default to "shot&lt;number&gt;" and can be changed.
    /// </summary>
    public static class ShotLibrary
    {
        public const string DataFile = "shot.json";

        [Serializable] public class ShotData
        {
            public string coordinates = "Unity: meters, y up, left-handed, floor at y=0";
            public string name, scene, created, speed;
            public int number, fps, width, height;
            public float verticalFovDeg;
            public CameraPathTool.SavedCamera[] keyframes, frames;
        }

        public class Shot
        {
            public string dir;
            public ShotData data;
            public int FrameCount => data.frames?.Length ?? 0;
            public float Seconds => data.fps > 0 ? FrameCount / (float)data.fps : 0;
            public bool HasFrames => File.Exists(Path.Combine(dir, "frame_0000.png"));
        }

        static string SceneDir => Path.Combine(Application.persistentDataPath, "Shots",
                                               SceneManager.GetActiveScene().name);
        static string CounterFile => Path.Combine(SceneDir, "counter.txt");

        /// <summary>Oldest first.</summary>
        public static List<Shot> List()
        {
            if (!Directory.Exists(SceneDir)) return new List<Shot>();
            return Directory.GetDirectories(SceneDir).OrderBy(d => d)
                .Select(Load).Where(s => s != null).ToList();
        }

        static Shot Load(string dir)
        {
            string file = Path.Combine(dir, DataFile);
            if (!File.Exists(file)) return null;
            try { return new Shot { dir = dir, data = JsonUtility.FromJson<ShotData>(File.ReadAllText(file)) }; }
            catch (Exception e) { Debug.LogWarning($"[VR Director] Skipping {dir}: {e.Message}"); return null; }
        }

        /// <summary>A new, empty shot folder with the next number and its default name.</summary>
        public static Shot Create(ShotData data)
        {
            Directory.CreateDirectory(SceneDir);
            int last = File.Exists(CounterFile) && int.TryParse(File.ReadAllText(CounterFile), out int n) ? n : 0;
            last = Math.Max(last, List().Select(s => s.data.number).DefaultIfEmpty(0).Max());
            data.number = last + 1;
            data.name = $"shot{data.number}";
            data.scene = SceneManager.GetActiveScene().name;
            data.created = DateTime.Now.ToString("yyyy-MM-dd HH:mm");
            File.WriteAllText(CounterFile, data.number.ToString());

            var shot = new Shot { dir = Path.Combine(SceneDir, DateTime.Now.ToString("yyyyMMdd_HHmmss")), data = data };
            Directory.CreateDirectory(shot.dir);
            Save(shot);
            return shot;
        }

        public static void Save(Shot shot) =>
            File.WriteAllText(Path.Combine(shot.dir, DataFile), JsonUtility.ToJson(shot.data, true));

        public static void Rename(Shot shot, string name)
        {
            name = name?.Trim();
            if (string.IsNullOrEmpty(name)) return;
            shot.data.name = name;
            Save(shot);
        }

        public static void Delete(Shot shot)
        {
            if (Directory.Exists(shot.dir)) Directory.Delete(shot.dir, true);
        }
    }
}
