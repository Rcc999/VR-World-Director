using System.IO;
using System.Linq;
using MixedReality.Toolkit.UX;
using TMPro;
using Unity.XR.CoreUtils;
using UnityEditor;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace VRDirector.Editor
{
    /// <summary>
    /// Adds the camera keyframe tools to a viewer scene: <see cref="CameraPathTool"/>,
    /// <see cref="ShotRenderer"/>, the MRTK hand menu with its buttons (<see cref="PathMenu"/>), and the
    /// materials they use. Called by both scene builders.
    /// </summary>
    static class CameraToolsBuilder
    {
        const string MaterialDir = "Assets/VRDirector/Materials";
        const string HandMenuPrefab = "Packages/org.mixedrealitytoolkit.uxcomponents.noncanvas/HandMenu/HandMenu.prefab";
        const string ButtonPrefab = "Packages/org.mixedrealitytoolkit.uxcomponents.noncanvas/Button/128x32/PressableButton_128x32mm_TextOnly.prefab";
        const string FontAsset = "Packages/org.mixedrealitytoolkit.standardassets/Fonts/Selawik-Semibold-MRTKIcons SDF.asset";
        const string TmpEssentials = "Packages/com.unity.ugui/Package Resources/TMP Essential Resources.unitypackage";

        internal static void Add(Scene scene, XROrigin origin)
        {
            ImportTmpEssentialsIfMissing();
            var body = UnlitMaterial("CameraBody", Color.white);
            var line = UnlitMaterial("PathLine", new Color(0.3f, 0.85f, 1f));
            var screen = UnlitMaterial("CameraScreen", Color.white);
            var font = AssetDatabase.LoadAssetAtPath<TMP_FontAsset>(FontAsset);
            if (font == null) Debug.LogError($"[VR Director] Missing font {FontAsset}");

            var locomotion = origin != null ? origin.GetComponent<VRLocomotion>() : null;
            if (locomotion != null) locomotion.lineMaterial = line;

            var toolGo = new GameObject("Camera Path Tool");
            SceneManager.MoveGameObjectToScene(toolGo, scene);
            var tool = toolGo.AddComponent<CameraPathTool>();
            tool.origin = origin;
            tool.locomotion = locomotion;
            tool.bodyMaterial = body;
            tool.lineMaterial = line;
            tool.screenMaterial = screen;
            tool.font = font;

            var shot = toolGo.AddComponent<ShotRenderer>();
            shot.tool = tool;
            shot.origin = origin;
            shot.screenMaterial = screen;
            shot.font = font;
            shot.locomotion = locomotion;

            var menuPrefab = AssetDatabase.LoadAssetAtPath<GameObject>(HandMenuPrefab);
            var buttonPrefab = AssetDatabase.LoadAssetAtPath<GameObject>(ButtonPrefab);
            if (menuPrefab == null || buttonPrefab == null)
            {
                Debug.LogError("[VR Director] MRTK HandMenu / button prefab not found; no menu added.");
                return;
            }
            var menuGo = (GameObject)PrefabUtility.InstantiatePrefab(menuPrefab, scene);
            menuGo.name = "Camera Menu (left palm)";
            var collection = menuGo.GetComponentsInChildren<Transform>(true).First(t => t.name == "ButtonCollection");
            var backplate = menuGo.GetComponentsInChildren<Transform>(true).First(t => t.name == "UX.HandMenu.Backplate");
            string[] labels = { "New camera", "Undo", "Clear all", "Save", "Speed: Medium", "Generate", "Reset position" };
            const float step = 0.036f; // 32 mm buttons + 4 mm gap
            backplate.localScale = new Vector3(0.136f, step * labels.Length + 0.004f, 0.02f);

            var buttons = new PressableButton[labels.Length];
            for (int i = 0; i < labels.Length; i++)
            {
                var b = (GameObject)PrefabUtility.InstantiatePrefab(buttonPrefab, collection);
                b.name = labels[i];
                b.transform.localPosition = new Vector3(0, step * ((labels.Length - 1) / 2f - i), -0.012f);
                buttons[i] = b.GetComponent<PressableButton>();
                PathMenu.SetLabel(b.transform, labels[i]);
            }

            var menu = menuGo.AddComponent<PathMenu>();
            menu.tool = tool;
            menu.shot = shot;
            shot.menu = menuGo;
            menu.locomotion = locomotion;
            (menu.newCamera, menu.undo, menu.clear, menu.save, menu.speed, menu.generate, menu.resetPosition) =
                (buttons[0], buttons[1], buttons[2], buttons[3], buttons[4], buttons[5], buttons[6]);
        }

        /// <summary>
        /// Puts the room on the "Scene" layer (created if missing): the only layer the
        /// shot and preview cameras render, so the video shows the room and nothing else.
        /// </summary>
        internal static void MarkAsScene(GameObject room)
        {
            int layer = EnsureLayer(SceneLayers.SceneName);
            if (layer >= 0) SceneLayers.SetLayerRecursively(room, layer);
        }

        static int EnsureLayer(string name)
        {
            int existing = LayerMask.NameToLayer(name);
            if (existing >= 0) return existing;
            var tagManager = new SerializedObject(AssetDatabase.LoadMainAssetAtPath("ProjectSettings/TagManager.asset"));
            var layers = tagManager.FindProperty("layers");
            for (int i = 8; i < layers.arraySize; i++) // 0-7 are Unity's built-in layers
            {
                var slot = layers.GetArrayElementAtIndex(i);
                if (!string.IsNullOrEmpty(slot.stringValue)) continue;
                slot.stringValue = name;
                tagManager.ApplyModifiedProperties();
                Debug.Log($"[VR Director] Created layer '{name}' (#{i}).");
                return i;
            }
            Debug.LogError($"[VR Director] No free layer for '{name}'; shots will include the tools.");
            return -1;
        }

        static Material UnlitMaterial(string name, Color color)
        {
            Directory.CreateDirectory(MaterialDir);
            string path = $"{MaterialDir}/{name}.mat";
            var mat = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (mat != null) return mat;
            mat = new Material(Shader.Find("Universal Render Pipeline/Unlit")) { color = color };
            AssetDatabase.CreateAsset(mat, path);
            return mat;
        }

        /// <summary>TextMeshPro needs its settings + default shaders imported once per project.</summary>
        static void ImportTmpEssentialsIfMissing()
        {
            if (Resources.Load<TMP_Settings>("TMP Settings") != null) return;
            if (!File.Exists(Path.GetFullPath(TmpEssentials)))
            {
                Debug.LogWarning("[VR Director] Import TMP Essential Resources (Window > TextMeshPro) for the labels.");
                return;
            }
            AssetDatabase.ImportPackage(TmpEssentials, false);
            Debug.Log("[VR Director] Imported TMP Essential Resources.");
        }
    }
}
