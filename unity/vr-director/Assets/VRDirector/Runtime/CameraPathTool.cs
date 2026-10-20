using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using TMPro;
using Unity.XR.CoreUtils;
using UnityEngine;

namespace VRDirector
{
    /// <summary>
    /// Camera keyframe editing (Step 2 of the project):
    /// - <see cref="NewCamera"/> puts a camera in your right hand, with a live preview
    ///   on its back; aim it and pinch (right hand) to place it where it is.
    /// - Placed cameras are numbered 1, 2, 3... in order and joined by a smooth path
    ///   (Catmull-Rom); pinch one to move or rotate it.
    /// - <see cref="Undo"/> removes the last camera, <see cref="Clear"/> all of them.
    /// - <see cref="Save"/> writes them to &lt;persistentDataPath&gt;/camera_path.json;
    ///   they are loaded back when the app starts.
    /// </summary>
    public class CameraPathTool : MonoBehaviour
    {
        public XROrigin origin;
        public VRLocomotion locomotion;
        public Material bodyMaterial, lineMaterial, screenMaterial;
        public TMP_FontAsset font;
        public Vector2Int previewSize = new(384, 216);

        [Tooltip("Where the held camera sits relative to the right pinch point, along the pointing direction (m).")]
        public float holdDistance = 0.12f;

        public IReadOnlyList<PathCamera> Cameras => cameras;
        public bool IsHolding => held != null;

        [Serializable] public class SavedCamera
        {
            public Vector3 position;
            public Quaternion rotation;
            public SavedCamera(Vector3 p, Quaternion r) { position = p; rotation = r; }
        }

        [Serializable] class SavedPath
        {
            public string coordinates = "Unity: meters, y up, left-handed, floor at y=0";
            public float verticalFovDeg = PathCamera.VerticalFov, aspect = PathCamera.Aspect;
            public SavedCamera[] cameras;
        }

        public static string SavePath => Path.Combine(Application.persistentDataPath, "camera_path.json");

        readonly List<PathCamera> cameras = new();
        PathCamera held;
        HandInput right;
        LineRenderer path;
        const int SamplesPerSegment = 20;

        void Awake()
        {
            if (origin == null) origin = FindFirstObjectByType<XROrigin>();
            right = new HandInput(Hand.Right);
            path = new GameObject("Path").AddComponent<LineRenderer>();
            path.transform.SetParent(transform, false);
            path.useWorldSpace = true;
            path.widthMultiplier = 0.008f;
            path.sharedMaterial = lineMaterial;
            path.positionCount = 0;
        }

        void Start() => Load();

        void OnEnable() => right.Enable();
        void OnDisable() => right.Disable();

        public void NewCamera()
        {
            if (held != null) return;
            held = PathCamera.Create(transform, bodyMaterial, lineMaterial, screenMaterial, font, previewSize);
            held.SetNumber(cameras.Count + 1);
            held.SetPreview(true);
            held.SetGrabbable(false);
            if (locomotion != null) locomotion.blockedHands.Add(Hand.Right);
            FollowHand(snap: true);
        }

        public void CancelHeld()
        {
            if (held == null) return;
            Destroy(held.gameObject);
            held = null;
            if (locomotion != null) locomotion.blockedHands.Remove(Hand.Right);
        }

        public void Undo()
        {
            if (held != null) { CancelHeld(); return; }
            if (cameras.Count == 0) return;
            Destroy(cameras[^1].gameObject);
            cameras.RemoveAt(cameras.Count - 1);
        }

        public void Clear()
        {
            CancelHeld();
            foreach (var c in cameras) Destroy(c.gameObject);
            cameras.Clear();
        }

        public void Save()
        {
            var data = new SavedPath
            {
                cameras = cameras.Select(c => new SavedCamera(c.transform.position, c.transform.rotation)).ToArray()
            };
            File.WriteAllText(SavePath, JsonUtility.ToJson(data, true));
            Debug.Log($"[VR Director] Saved {cameras.Count} cameras to {SavePath}");
        }

        void Load()
        {
            if (!File.Exists(SavePath)) return;
            var data = JsonUtility.FromJson<SavedPath>(File.ReadAllText(SavePath));
            foreach (var c in data?.cameras ?? Array.Empty<SavedCamera>())
            {
                var cam = PathCamera.Create(transform, bodyMaterial, lineMaterial, screenMaterial, font, previewSize);
                cam.transform.SetPositionAndRotation(c.position, c.rotation);
                cameras.Add(cam);
            }
            Debug.Log($"[VR Director] Loaded {cameras.Count} cameras from {SavePath}");
        }

        /// <summary>Lock or unlock all camera editing (while a shot renders).</summary>
        public void SetInteractive(bool on)
        {
            if (!on) CancelHeld();
            foreach (var c in cameras) c.SetGrabbable(on);
            enabled = on;
        }

        void Update()
        {
            right.Update();
            if (held != null)
            {
                FollowHand(snap: false);
                if (right.PinchStarted) Place();
            }
            DrawPath();
        }

        void Place()
        {
            held.SetPreview(false);
            held.SetGrabbable(true);
            cameras.Add(held);
            held = null;
            // The pinch that placed the camera already started blocked, so it will not
            // turn into a drag; free the hand for the next pinch.
            if (locomotion != null) locomotion.blockedHands.Remove(Hand.Right);
        }

        void FollowHand(bool snap)
        {
            if (!right.IsTracked && !snap) return;
            var space = HandInput.TrackingSpace(origin);
            Quaternion aim = space.rotation * right.AimRotation;
            Vector3 pos = space.TransformPoint(right.PinchPosition) + aim * Vector3.forward * holdDistance;
            Quaternion rot = PathCamera.Level(aim);
            var t = held.transform;
            float k = snap ? 1f : 1f - Mathf.Exp(-20f * Time.deltaTime); // light smoothing of hand jitter
            t.SetPositionAndRotation(Vector3.Lerp(t.position, pos, k), Quaternion.Slerp(t.rotation, rot, k));
        }

        // --- path -------------------------------------------------------------

        void DrawPath()
        {
            for (int i = 0; i < cameras.Count; i++) cameras[i].SetNumber(i + 1);
            var pts = cameras.Select(c => c.transform.position).ToList();
            if (held != null) pts.Add(held.transform.position); // preview where the next camera would go
            if (pts.Count < 2) { path.positionCount = 0; return; }
            int n = (pts.Count - 1) * SamplesPerSegment + 1;
            path.positionCount = n;
            for (int i = 0; i < n; i++)
                path.SetPosition(i, CatmullRom(pts, (float)i / SamplesPerSegment));
        }

        /// <summary>Uniform Catmull-Rom through the points, t in [0, count - 1].</summary>
        public static Vector3 CatmullRom(IReadOnlyList<Vector3> p, float t)
        {
            int last = p.Count - 1;
            int i = Mathf.Clamp(Mathf.FloorToInt(t), 0, last - 1);
            float u = t - i;
            Vector3 p0 = p[Mathf.Max(i - 1, 0)], p1 = p[i], p2 = p[i + 1], p3 = p[Mathf.Min(i + 2, last)];
            return 0.5f * (2 * p1 + (p2 - p0) * u + (2 * p0 - 5 * p1 + 4 * p2 - p3) * u * u
                           + (3 * p1 - p0 - 3 * p2 + p3) * u * u * u);
        }
    }
}
