using System.Collections.Generic;
using System.IO;
using MixedReality.Toolkit.UX;
using TMPro;
using Unity.XR.CoreUtils;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace VRDirector
{
    /// <summary>
    /// Scene picker: one button per world in the build (the 3DGS room, the Puffin
    /// scenes...). Pressing one loads that Unity scene; each scene keeps its own
    /// cameras (camera_path) and shots. The current world's button is greyed out and shown as "&gt; Name &lt;".
    /// </summary>
    public class WorldsPanel : MonoBehaviour
    {
        public XROrigin origin;
        public ShotRenderer shotRenderer;
        public TMP_FontAsset font;
        public Material backgroundMaterial;
        [Tooltip("World buttons, top to bottom; extra ones are hidden.")]
        public PressableButton[] worldButtons;
        public PressableButton close;

        public const float Width = 0.30f, Step = 0.036f, Top = 0.05f;
        const int MaxPerColumn = 6;     // more worlds than this: two columns
        const float ColumnStep = 0.144f; // 128 mm buttons + 16 mm gap

        public bool IsOpen => gameObject.activeSelf;

        TextMeshPro title;
        bool loading;

        void Awake()
        {
            if (origin == null) origin = FindFirstObjectByType<XROrigin>();
            var bg = GameObject.CreatePrimitive(PrimitiveType.Quad);
            bg.name = "Background";
            Destroy(bg.GetComponent<Collider>());
            bg.transform.SetParent(transform, false);
            bg.GetComponent<Renderer>().sharedMaterial = backgroundMaterial;

            title = new GameObject("Title").AddComponent<TextMeshPro>();
            title.transform.SetParent(transform, false);
            title.transform.localPosition = new Vector3(0, Top + 0.025f, -0.005f);
            title.font = font;
            title.fontSize = 0.35f;
            title.alignment = TextAlignmentOptions.Center;
            title.rectTransform.sizeDelta = new Vector2(Width - 0.02f, 0.04f);

            var worlds = Worlds();
            string current = SceneManager.GetActiveScene().path;
            int count = Mathf.Min(worlds.Count, worldButtons.Length);
            int columns = count > MaxPerColumn ? 2 : 1, perColumn = Mathf.CeilToInt(count / (float)columns);
            for (int i = 0; i < worldButtons.Length; i++)
            {
                var b = worldButtons[i];
                bool used = i < worlds.Count;
                b.gameObject.SetActive(used);
                if (!used) continue;
                int col = i / perColumn, row = i % perColumn;
                b.transform.localPosition = new Vector3(columns == 2 ? (col - 0.5f) * ColumnStep : 0,
                                                        Top - row * Step, b.transform.localPosition.z);
                string path = worlds[i];
                bool here = path == current;
                PathMenu.SetLabel(b, here ? $"> {DisplayName(path)} <" : DisplayName(path));
                b.enabled = !here;
                b.OnClicked.AddListener(() => Load(path));
            }
            int rows = perColumn + 1; // + Close
            if (close != null)
            {
                close.transform.localPosition = new Vector3(0, Top - Step * (rows - 1), -0.012f);
                close.OnClicked.AddListener(Close);
            }
            float height = Step * rows + 0.04f;
            bg.transform.localScale = new Vector3(columns == 2 ? Width + ColumnStep : Width, height, 1);
            bg.transform.localPosition = new Vector3(0, Top + 0.05f - height / 2, 0);
            title.text = "<b>Worlds</b>";
            gameObject.SetActive(false);
        }

        /// <summary>Scenes enabled in the build, in build order.</summary>
        public static List<string> Worlds()
        {
            var list = new List<string>();
            for (int i = 0; i < SceneManager.sceneCountInBuildSettings; i++)
                list.Add(SceneUtility.GetScenePathByBuildIndex(i));
            return list;
        }

        /// <summary>Short button label: "SplatViewer" → "Room 3DGS", "Puffin-Indoor" → "Indoor".</summary>
        public static string DisplayName(string scenePath)
        {
            string name = Path.GetFileNameWithoutExtension(scenePath);
            if (name == "SplatViewer") return "Room 3DGS";
            if (name == "PointCloudViewer") return "Point cloud";
            return name.StartsWith("Puffin-") ? name.Substring(7) : name;
        }

        public void Open()
        {
            var head = origin.Camera.transform;
            Vector3 fwd = Vector3.ProjectOnPlane(head.forward, Vector3.up).normalized;
            if (fwd.sqrMagnitude < 1e-4f) fwd = Vector3.forward;
            transform.SetPositionAndRotation(head.position + fwd * 0.55f - 0.15f * Vector3.up,
                                             Quaternion.LookRotation(fwd, Vector3.up));
            gameObject.SetActive(true);
        }

        public void Close() => gameObject.SetActive(false);

        public void Toggle()
        {
            if (IsOpen) Close(); else Open();
        }

        void Load(string path)
        {
            if (loading || (shotRenderer != null && shotRenderer.IsBusy)) return;
            loading = true;
            if (shotRenderer != null) shotRenderer.Stop();
            title.text = $"<b>Loading {DisplayName(path)}...</b>";
            foreach (var b in worldButtons) b.enabled = false;
            SceneManager.LoadSceneAsync(path, LoadSceneMode.Single);
        }
    }
}
