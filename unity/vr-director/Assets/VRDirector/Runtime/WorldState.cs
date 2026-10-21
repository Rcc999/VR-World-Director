using System;
using TMPro;
using Unity.XR.CoreUtils;
using UnityEngine;
using UnityEngine.Video;

namespace VRDirector
{
    /// <summary>
    /// The world states the server exports for a scene (server/generation/WORLD_STATE.md):
    /// appearance (RGB), geometry (depth) and physics (gravity, Puffin's perspective field).
    /// Baked from world_state.json by the World State scene builder; driven by
    /// <see cref="WorldStatePanel"/>:
    /// show / hide the generated cloud, color the clouds by photo / height / depth,
    /// a gravity arrow + horizon ring at eye height, and replays of each camera run
    /// (RGB, depth, up-vector or latitude field) on a screen, with the frame's camera
    /// shown in the scene and its roll / pitch (scene, conditioned, measured).
    /// Every world state is its own Unity scene in Assets/Scenes/WorldStates/, switched
    /// with the Worlds panel like every other world.
    /// </summary>
    public class WorldState : MonoBehaviour
    {
        [Serializable]
        public class Angles
        {
            public bool valid;
            public float roll, pitch;
            public override string ToString() => valid ? $"{roll:+0.0;-0.0} / {pitch:+0.0;-0.0}" : "  -";
        }

        [Serializable]
        public class View
        {
            public Vector3 position;
            public Quaternion rotation;
            public Angles scene = new(), conditioned = new(), measured = new();
        }

        [Serializable]
        public class Run
        {
            public string name;
            public bool generated;
            public float vfov;
            public VideoClip rgb, depth, pfUp, pfLat;
            public View[] views;
        }

        public enum ColorMode { Photo, Height, Depth }
        public enum Layer { RGB, Depth, UpField, Latitude }

        [Header("From world_state.json")]
        public string sceneName;
        public string kind;
        [TextArea] public string caption;
        [TextArea] public string physicsCheck;
        public Vector3 gravity = Vector3.down;
        public Run[] runs = Array.Empty<Run>();

        [Header("Scene")]
        public GameObject realCloud;
        public GameObject generatedCloud;
        public XROrigin origin;
        public Material lineMaterial;
        public Material screenMaterial;
        public TMP_FontAsset font;

        public bool ShowGenerated { get; private set; } = true;
        public ColorMode Colors { get; private set; } = ColorMode.Photo;
        public bool GravityShown => gravityRoot != null && gravityRoot.activeSelf;
        public int RunIndex { get; private set; }
        public Run CurrentRun => runs.Length > 0 ? runs[RunIndex] : null;
        public Layer CurrentLayer { get; private set; } = Layer.RGB;
        public bool IsReplaying => screen != null && screen.activeSelf;
        public bool HasGenerated => generatedCloud != null;

        static readonly int ColorModeId = Shader.PropertyToID("_VRDColorMode");
        static readonly int HeightMaxId = Shader.PropertyToID("_VRDHeightMax");
        static readonly int DepthMaxId = Shader.PropertyToID("_VRDDepthMax");

        GameObject gravityRoot, screen, videoQuad, marker;
        Transform gravityArrow;
        LineRenderer horizon, markerLines;
        VideoPlayer player;
        RenderTexture videoTexture;
        TextMeshPro screenText;
        long pendingFrame = -1;

        void Awake()
        {
            if (origin == null) origin = FindFirstObjectByType<XROrigin>();
            SetColors(ColorMode.Photo);
            BuildGravity();
            BuildScreen();
            BuildMarker();
        }

        void OnDestroy()
        {
            Shader.SetGlobalFloat(ColorModeId, 0); // globals outlive the scene in the editor
            if (videoTexture != null) videoTexture.Release();
        }

        /// <summary>Folder of the world state scenes (listed in the Worlds panel with the other worlds).</summary>
        public const string ScenesFolder = "Assets/Scenes/WorldStates/";

        // --- Appearance / geometry ------------------------------------------------

        public void ToggleGenerated()
        {
            if (generatedCloud == null) return;
            ShowGenerated = !ShowGenerated;
            generatedCloud.SetActive(ShowGenerated);
        }

        public void CycleColors() => SetColors((ColorMode)(((int)Colors + 1) % 3));

        void SetColors(ColorMode mode)
        {
            Colors = mode;
            Shader.SetGlobalFloat(ColorModeId, (int)mode);
            Shader.SetGlobalFloat(HeightMaxId, 3f);  // floor (blue) to 3 m (red)
            Shader.SetGlobalFloat(DepthMaxId, 8f);   // you (red) to 8 m (blue)
        }

        // --- Physics: gravity arrow + horizon at eye height --------------------------

        public void ToggleGravity() => gravityRoot.SetActive(!gravityRoot.activeSelf);

        void BuildGravity()
        {
            gravityRoot = new GameObject("Gravity + Horizon");
            gravityRoot.transform.SetParent(transform, false);

            horizon = NewLine("Horizon", gravityRoot.transform, 0.006f, new Color(1f, 0.85f, 0.2f));
            horizon.loop = true;
            const int segments = 96;
            horizon.positionCount = segments;
            for (int i = 0; i < segments; i++)
            {
                float a = i * Mathf.PI * 2 / segments;
                horizon.SetPosition(i, new Vector3(Mathf.Cos(a), 0, Mathf.Sin(a)) * 2.5f); // 2.5 m around you
            }

            var arrow = NewLine("Gravity Arrow", gravityRoot.transform, 0.012f, new Color(0.3f, 1f, 0.4f));
            arrow.positionCount = 5; // shaft + head, drawn in the arrow's local frame
            arrow.SetPositions(new[]
            {
                Vector3.zero, new Vector3(0, -0.5f, 0), new Vector3(-0.06f, -0.4f, 0),
                new Vector3(0, -0.5f, 0), new Vector3(0.06f, -0.4f, 0),
            });
            arrow.transform.localRotation = Quaternion.FromToRotation(Vector3.down, gravity.normalized);
            gravityArrow = arrow.transform;
            gravityRoot.SetActive(false);
        }

        void LateUpdate()
        {
            if (gravityRoot.activeSelf && origin != null)
            {
                // Ring centered on you at eye height; the arrow 0.8 m ahead, from eye height down.
                var head = origin.Camera.transform;
                gravityRoot.transform.position = head.position;
                Vector3 fwd = Vector3.ProjectOnPlane(head.forward, Vector3.up).normalized;
                gravityArrow.position = head.position + fwd * 0.8f;
            }
            if (IsReplaying) UpdateReplay();
        }

        // --- Replays: rgb / depth / pf_up / pf_lat videos of each run ----------------------

        public void NextRun(int step)
        {
            if (runs.Length == 0) return;
            RunIndex = (RunIndex + step % runs.Length + runs.Length) % runs.Length;
            if (IsReplaying) PlayClip(0);
        }

        public void CycleLayer()
        {
            CurrentLayer = (Layer)(((int)CurrentLayer + 1) % 4);
            if (IsReplaying) PlayClip(player.frame); // same frame, other state
        }

        /// <summary>Plays the current run on a screen centered at <paramref name="position"/>, or stops it.</summary>
        public void ToggleReplay(Vector3 position, Quaternion rotation)
        {
            if (IsReplaying) StopReplay();
            else if (CurrentRun != null)
            {
                screen.transform.SetPositionAndRotation(position, rotation);
                screen.SetActive(true);
                marker.SetActive(true);
                PlayClip(0);
            }
        }

        public void StopReplay()
        {
            if (player != null) player.Stop();
            screen.SetActive(false);
            marker.SetActive(false);
        }

        VideoClip ClipFor(Run run, Layer layer) => layer switch
        {
            Layer.Depth => run.depth,
            Layer.UpField => run.pfUp,
            Layer.Latitude => run.pfLat,
            _ => run.rgb,
        };

        void PlayClip(long frame)
        {
            var clip = ClipFor(CurrentRun, CurrentLayer);
            if (clip == null) { screenText.text = $"{CurrentRun.name}: no {CurrentLayer} video"; return; }
            // Screen 0.45 m wide (or tall) at the video's aspect, sitting right above the panel.
            float aspect = clip.width / (float)Mathf.Max(1, clip.height);
            var size = aspect >= 1 ? new Vector2(0.45f, 0.45f / aspect) : new Vector2(0.45f * aspect, 0.45f);
            videoQuad.transform.localScale = new Vector3(size.x, size.y, 1);
            screenText.transform.localPosition = new Vector3(0, size.y / 2 + 0.035f, -0.005f);
            if (videoTexture == null || videoTexture.width != clip.width || videoTexture.height != clip.height)
            {
                if (videoTexture != null) videoTexture.Release();
                videoTexture = new RenderTexture((int)clip.width, (int)clip.height, 0) { name = "World State Video" };
                player.targetTexture = videoTexture;
                videoQuad.GetComponent<Renderer>().material.mainTexture = videoTexture;
            }
            player.clip = clip;
            pendingFrame = frame;
            player.Play();
        }

        void UpdateReplay()
        {
            var run = CurrentRun;
            if (pendingFrame >= 0 && player.isPrepared)
            {
                player.frame = pendingFrame;
                pendingFrame = -1;
            }
            int n = run.views.Length;
            int i = n == 0 ? 0 : Mathf.Clamp((int)Mathf.Max(0, player.frame), 0, n - 1);
            if (n > 0) PlaceMarker(run.views[i], run.vfov, player.clip.width / (float)Mathf.Max(1, player.clip.height));
            var v = n > 0 ? run.views[i] : null;
            string layerName = CurrentLayer switch
            {
                Layer.UpField => "up-vector field", Layer.Latitude => "latitude field",
                Layer.Depth => "depth (red = near)", _ => "RGB",
            };
            screenText.text =
                $"<b>{run.name}</b> {(run.generated ? "generated" : "real")} - {layerName} - frame {i + 1}/{n}\n" +
                (v == null ? "" :
                 $"roll / pitch (deg)   scene {v.scene}   " +
                 (run.generated ? $"told {v.conditioned}   " : "") +
                 $"measured {v.measured}");
        }

        // --- Building blocks ------------------------------------------------------------

        void BuildScreen()
        {
            // Unscaled root: the video quad is scaled to the clip's aspect, the caption is not.
            screen = new GameObject("World State Screen");
            screen.transform.SetParent(transform, false);
            videoQuad = GameObject.CreatePrimitive(PrimitiveType.Quad);
            videoQuad.name = "Video";
            Destroy(videoQuad.GetComponent<Collider>());
            videoQuad.transform.SetParent(screen.transform, false);
            videoQuad.GetComponent<Renderer>().material = new Material(screenMaterial);

            player = videoQuad.AddComponent<VideoPlayer>();
            player.playOnAwake = false;
            player.isLooping = true;
            player.renderMode = VideoRenderMode.RenderTexture;
            player.audioOutputMode = VideoAudioOutputMode.None;

            // Above the video (the World panel sits right below it).
            screenText = new GameObject("Caption").AddComponent<TextMeshPro>();
            screenText.transform.SetParent(screen.transform, false);
            screenText.font = font;
            screenText.fontSize = 0.14f;
            screenText.alignment = TextAlignmentOptions.Bottom;
            screenText.rectTransform.sizeDelta = new Vector2(0.62f, 0.06f);
            screen.SetActive(false);
        }

        /// <summary>Wire frustum (0.3 m deep) at the replayed frame's camera.</summary>
        void BuildMarker()
        {
            marker = new GameObject("Replay Camera");
            marker.transform.SetParent(transform, false);
            markerLines = NewLine("Frustum", marker.transform, 0.005f, new Color(1f, 0.35f, 0.9f));
            marker.SetActive(false);
        }

        void PlaceMarker(View view, float vfov, float aspect)
        {
            marker.transform.SetPositionAndRotation(view.position, view.rotation);
            float d = 0.3f, h = d * Mathf.Tan(vfov * 0.5f * Mathf.Deg2Rad), w = h * aspect;
            var o = Vector3.zero;
            var c = new[] { new Vector3(-w, -h, d), new Vector3(w, -h, d), new Vector3(w, h, d), new Vector3(-w, h, d) };
            // One strip covering the 4 image edges and the 4 edges to the camera center.
            markerLines.positionCount = 10;
            markerLines.SetPositions(new[] { c[0], c[1], c[2], c[3], c[0], o, c[1], c[2], o, c[3] });
        }

        LineRenderer NewLine(string name, Transform parent, float width, Color color)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            var line = go.AddComponent<LineRenderer>();
            line.useWorldSpace = false;
            line.widthMultiplier = width;
            line.material = new Material(lineMaterial) { color = color }; // unlit: color from the material
            line.numCapVertices = 2;
            return line;
        }
    }
}
