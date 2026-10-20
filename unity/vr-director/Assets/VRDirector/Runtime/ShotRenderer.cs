using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using GaussianSplatting.Runtime;
using TMPro;
using Unity.XR.CoreUtils;
using UnityEngine;
using UnityEngine.Experimental.Rendering;
using UnityEngine.Rendering;

namespace VRDirector
{
    /// <summary>
    /// Step 3 with the 3DGS scene: renders the shot along the camera path.
    ///
    /// <see cref="Generate"/> flies a hidden camera through the placed cameras
    /// (Catmull-Rom positions, slerped rotations, constant Slow / Medium / Fast speed), renders one frame
    /// per app frame into a texture and saves it as PNG, plus trajectory.json, under
    /// &lt;persistentDataPath&gt;/Shots/&lt;date&gt;/. A floating screen shows the
    /// progress, then replays the shot in a loop. server/shots/pull_shot.sh copies
    /// the latest shot to the Mac and makes an MP4.
    /// </summary>
    public class ShotRenderer : MonoBehaviour
    {
        public CameraPathTool tool;
        public XROrigin origin;
        public VRLocomotion locomotion;
        [Tooltip("Hand menu root, hidden while a shot renders.")]
        public GameObject menu;
        public Material screenMaterial;
        public TMP_FontAsset font;

        [Tooltip("Shot resolution (16:9 to match the camera models' view cones).")]
        public Vector2Int resolution = new(1280, 720);
        public int fps = 30;

        public enum Speed { Slow, Medium, Fast }

        [Tooltip("Slow / Medium / Fast = 0.25 / 0.5 / 1 m/s along the path (turns: 22 / 45 / 90 deg/s).")]
        public Speed speed = Speed.Medium;

        float MetersPerSecond => speed switch { Speed.Slow => 0.25f, Speed.Fast => 1f, _ => 0.5f };
        float DegreesPerSecond => MetersPerSecond * 90f; // a camera that only rotates still gets time

        public void CycleSpeed() => speed = (Speed)(((int)speed + 1) % 3);

        public bool IsBusy => rendering;
        public bool ScreenVisible => screen != null && screen.activeSelf;

        Camera shotCam;
        RenderTexture rt;
        GameObject screen;
        TextMeshPro status;
        bool rendering;
        List<Pose> frames;
        Coroutine replay;

        void Awake()
        {
            if (origin == null) origin = FindFirstObjectByType<XROrigin>();
            rt = new RenderTexture(resolution.x, resolution.y, 24, RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB)
                { name = "Shot" };
            var camGo = new GameObject("Shot Camera");
            camGo.transform.SetParent(transform, false);
            shotCam = camGo.AddComponent<Camera>();
            shotCam.stereoTargetEye = StereoTargetEyeMask.None;
            shotCam.targetTexture = rt;
            shotCam.fieldOfView = PathCamera.VerticalFov;
            shotCam.aspect = (float)resolution.x / resolution.y;
            shotCam.nearClipPlane = 0.02f;
            shotCam.farClipPlane = 50f;
            shotCam.clearFlags = CameraClearFlags.SolidColor;
            shotCam.backgroundColor = Color.black;
            shotCam.cullingMask = SceneLayers.SceneMask; // the room only: no hands, menus, cameras
            shotCam.enabled = false;
            BuildScreen();
        }

        public void Generate()
        {
            if (rendering) return;
            frames = SampleFrames(tool.Cameras.Select(c => new Pose(c.transform.position, c.transform.rotation)).ToList());
            if (frames == null)
            {
                ShowScreen($"Place at least 2 cameras first");
                return;
            }
            if (replay != null) StopCoroutine(replay);
            StartCoroutine(Render());
        }

        public void HideScreen()
        {
            if (rendering) return;
            if (replay != null) StopCoroutine(replay);
            replay = null;
            shotCam.enabled = false;
            screen.SetActive(false);
        }

        IEnumerator Render()
        {
            rendering = true;
            Isolate(true);
            string dir = Path.Combine(Application.persistentDataPath, "Shots", DateTime.Now.ToString("yyyyMMdd_HHmmss"));
            Directory.CreateDirectory(dir);
            File.WriteAllText(Path.Combine(dir, "trajectory.json"), TrajectoryJson());

            // Exact sort and full resolution for the shot; the headset view gets slower meanwhile.
            var splats = FindObjectsByType<GaussianSplatRenderer>(FindObjectsSortMode.None);
            var saved = splats.Select(s => (s.m_SortPasses, s.m_RenderScale)).ToArray();
            foreach (var s in splats) { s.m_SortPasses = 4; s.m_RenderScale = 1f; }

            shotCam.enabled = true;
            int pending = 0;
            var writes = new List<Task>();
            for (int i = 0; i < frames.Count; i++)
            {
                shotCam.transform.SetPositionAndRotation(frames[i].position, frames[i].rotation);
                yield return new WaitForEndOfFrame(); // this frame's render is done
                string path = Path.Combine(dir, $"frame_{i:D4}.png");
                pending++;
                AsyncGPUReadback.Request(rt, 0, TextureFormat.RGBA32, req =>
                {
                    if (!req.hasError)
                    {
                        byte[] raw = req.GetData<byte>().ToArray();
                        writes.Add(Task.Run(() => File.WriteAllBytes(path,
                            ImageConversion.EncodeArrayToPNG(raw, GraphicsFormat.R8G8B8A8_SRGB,
                                                             (uint)resolution.x, (uint)resolution.y))));
                    }
                    pending--;
                });
                SetStatus($"Rendering {i + 1}/{frames.Count}");
                while (pending > 4) yield return null; // keep memory bounded
            }
            while (pending > 0) yield return null;
            while (writes.Any(w => !w.IsCompleted)) yield return null;

            for (int i = 0; i < splats.Length; i++) (splats[i].m_SortPasses, splats[i].m_RenderScale) = saved[i];
            Isolate(false);
            rendering = false;
            Debug.Log($"[VR Director] Shot saved: {frames.Count} frames in {dir}");
            SetStatus($"Saved {frames.Count} frames ({frames.Count / (float)fps:F1} s)\n{Path.GetFileName(dir)}");
            replay = StartCoroutine(Replay());
        }

        int headsetMask;

        /// <summary>
        /// While rendering, the person waits in an empty black space with only the
        /// progress screen (the headset shows only the "UI" layer), and nothing can be
        /// touched: menu hidden, cameras locked, no movement.
        /// </summary>
        void Isolate(bool on)
        {
            var head = origin.Camera;
            if (on)
            {
                headsetMask = head.cullingMask;
                if (SceneLayers.Overlay >= 0) head.cullingMask = 1 << SceneLayers.Overlay;
            }
            else head.cullingMask = headsetMask;
            if (menu != null) menu.SetActive(!on);
            tool.SetInteractive(!on);
            if (locomotion != null) locomotion.enabled = !on;
        }

        /// <summary>Plays the shot on the screen in a loop (live render along the same path).</summary>
        IEnumerator Replay()
        {
            shotCam.enabled = true;
            while (true)
            {
                foreach (var f in frames)
                {
                    shotCam.transform.SetPositionAndRotation(f.position, f.rotation);
                    yield return new WaitForSeconds(1f / fps);
                }
                yield return new WaitForSeconds(0.5f);
            }
        }

        // --- path sampling ----------------------------------------------------

        /// <summary>
        /// Frames along the path: per segment, duration = max(length / speed,
        /// turn / maxTurnSpeed, 0.5 s); positions by arc length on the Catmull-Rom
        /// curve, rotation slerped over the segment. Null if fewer than 2 cameras.
        /// </summary>
        List<Pose> SampleFrames(List<Pose> keys)
        {
            if (keys.Count < 2) return null;
            var pts = keys.Select(k => k.position).ToList();
            var result = new List<Pose>();
            const int dense = 64;
            for (int s = 0; s < keys.Count - 1; s++)
            {
                var cum = new float[dense + 1];
                Vector3 prev = pts[s];
                for (int j = 1; j <= dense; j++)
                {
                    Vector3 p = CameraPathTool.CatmullRom(pts, s + (float)j / dense);
                    cum[j] = cum[j - 1] + Vector3.Distance(prev, p);
                    prev = p;
                }
                float length = cum[dense];
                float turn = Quaternion.Angle(keys[s].rotation, keys[s + 1].rotation);
                float seconds = Mathf.Max(length / MetersPerSecond, turn / DegreesPerSecond, 0.5f);
                int n = Mathf.Max(1, Mathf.RoundToInt(seconds * fps));
                for (int k = 0; k < n; k++)
                {
                    float u = ArcLengthToU(cum, length * k / n);
                    result.Add(new Pose(CameraPathTool.CatmullRom(pts, s + u),
                                        PathCamera.Level(Quaternion.Slerp(keys[s].rotation, keys[s + 1].rotation, u))));
                }
            }
            result.Add(keys[^1]);
            return result;
        }

        static float ArcLengthToU(float[] cum, float target)
        {
            int dense = cum.Length - 1;
            for (int j = 1; j <= dense; j++)
                if (cum[j] >= target)
                {
                    float a = cum[j - 1], b = cum[j];
                    return (j - 1 + (b > a ? (target - a) / (b - a) : 0)) / dense;
                }
            return 1f;
        }

        [Serializable] class Trajectory
        {
            public string coordinates = "Unity: meters, y up, left-handed, floor at y=0";
            public string speed;
            public int fps, width, height;
            public float verticalFovDeg;
            public CameraPathTool.SavedCamera[] keyframes, frames;
        }

        string TrajectoryJson() => JsonUtility.ToJson(new Trajectory
        {
            speed = speed.ToString(), fps = fps, width = resolution.x, height = resolution.y, verticalFovDeg = PathCamera.VerticalFov,
            keyframes = tool.Cameras.Select(c => new CameraPathTool.SavedCamera(c.transform.position, c.transform.rotation)).ToArray(),
            frames = frames.Select(f => new CameraPathTool.SavedCamera(f.position, f.rotation)).ToArray(),
        }, true);

        // --- screen -----------------------------------------------------------

        void BuildScreen()
        {
            screen = GameObject.CreatePrimitive(PrimitiveType.Quad);
            screen.name = "Shot Screen";
            screen.transform.SetParent(transform, false);
            screen.transform.localScale = new Vector3(0.8f, 0.8f * resolution.y / resolution.x, 1);
            screen.GetComponent<Renderer>().material = new Material(screenMaterial) { mainTexture = rt };
            Destroy(screen.GetComponent<Collider>());
            if (SceneLayers.Overlay >= 0) screen.layer = SceneLayers.Overlay;

            status = new GameObject("Status").AddComponent<TextMeshPro>();
            status.transform.SetParent(screen.transform, false);
            status.transform.localPosition = new Vector3(0, -0.6f, 0);
            status.transform.localScale = new Vector3(1 / 0.8f, 1 / (0.8f * resolution.y / resolution.x), 1);
            status.font = font;
            status.fontSize = 0.4f;
            status.alignment = TextAlignmentOptions.Center;
            status.rectTransform.sizeDelta = new Vector2(0.8f, 0.12f);
            status.gameObject.layer = screen.layer;
            screen.SetActive(false);
        }

        void ShowScreen(string text = null)
        {
            if (!screen.activeSelf)
            {
                // 1.4 m in front of the head, level, facing you.
                var head = origin.Camera.transform;
                Vector3 fwd = Vector3.ProjectOnPlane(head.forward, Vector3.up).normalized;
                screen.transform.SetPositionAndRotation(head.position + fwd * 1.4f, Quaternion.LookRotation(fwd, Vector3.up));
                screen.SetActive(true);
            }
            if (text != null) status.text = text;
        }

        void SetStatus(string text) => ShowScreen(text);
    }
}
