using System.IO;
using System.Linq;
using MixedReality.Toolkit.SpatialManipulation;
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
            var content = menuGo.GetComponentsInChildren<Transform>(true).First(t => t.name == "MenuContent");
            var panelBlack = UnlitMaterial("PanelBlack", Color.black);
            backplate.GetComponent<Renderer>().sharedMaterial = panelBlack; // readable over a bright room
            content.localScale = Vector3.one * 0.85f;
            // Beside the hand, on the thumb side (to the right of the left hand, toward the
            // right hand that presses the buttons), not over it.
            foreach (var hc in menuGo.GetComponentsInChildren<HandConstraint>(true))
            {
                hc.SafeZone = HandConstraint.SolverSafeZone.RadialSide;
                hc.SafeZoneBuffer = 0.17f;
            }
            // Two columns: cameras on the left, shot on the right.
            string[] labels = { "New camera", "Undo", "Clear all", "Save", "Reset position",
                                "Speed: Medium", "Generate", "Shots", "Help" };
            const int rows = 5;
            const float step = 0.036f, column = 0.132f; // 128x32 mm buttons + 4 mm gaps
            backplate.localScale = new Vector3(2 * column + 0.004f, step * rows + 0.004f, 0.02f);

            var buttons = new PressableButton[labels.Length];
            // MRTK's backplate material is rebound at runtime, so add our own black backing too.
            AddBacking(content, new Vector2(2 * column + 0.01f, step * rows + 0.01f), 0.012f);
            for (int i = 0; i < labels.Length; i++)
            {
                var b = (GameObject)PrefabUtility.InstantiatePrefab(buttonPrefab, collection);
                b.name = labels[i];
                int col = i / rows, row = i % rows;
                b.transform.localPosition = new Vector3((col - 0.5f) * column, step * ((rows - 1) / 2f - row), -0.012f);
                buttons[i] = b.GetComponent<PressableButton>();
                StyleButton(b, labels[i]);
            }

            // UI layer: the menu stays visible while you ride a shot (headset then shows Scene + UI).
            SceneLayers.SetLayerRecursively(menuGo, LayerMask.NameToLayer("UI"));
            var menu = menuGo.AddComponent<PathMenu>();
            menu.tool = tool;
            menu.shot = shot;
            shot.menu = menuGo;
            menu.locomotion = locomotion;
            (menu.newCamera, menu.undo, menu.clear, menu.save, menu.resetPosition) =
                (buttons[0], buttons[1], buttons[2], buttons[3], buttons[4]);
            (menu.speed, menu.generate, menu.shotsButton, menu.helpButton) = (buttons[5], buttons[6], buttons[7], buttons[8]);
            menu.help = AddHelpPanel(scene, origin, font, buttonPrefab);
            menu.shots = AddShotsPanel(scene, origin, font, buttonPrefab, tool, shot, locomotion);
        }

        const string KeyboardPrefab = "Packages/org.mixedrealitytoolkit.uxcomponents/Experimental/NonNativeKeyboard/TouchableNonNativeKeyboard.prefab";

        /// <summary>The shots panel: info text + 2 rows of 4 buttons, and the touch keyboard for renaming.</summary>
        static ShotsPanel AddShotsPanel(Scene scene, XROrigin origin, TMP_FontAsset font, GameObject buttonPrefab,
                                        CameraPathTool tool, ShotRenderer shot, VRLocomotion locomotion)
        {
            var go = new GameObject("Shots Panel");
            SceneManager.MoveGameObjectToScene(go, scene);
            string[] labels = { "< Prev", "Next >", "Watch", "Ride", "Edit", "Rename", "Delete", "Close" };
            var b = new PressableButton[labels.Length];
            for (int i = 0; i < labels.Length; i++)
            {
                var btn = (GameObject)PrefabUtility.InstantiatePrefab(buttonPrefab, go.transform);
                btn.name = labels[i];
                int col = i % 4, row = i / 4;
                btn.transform.localPosition = new Vector3((col - 1.5f) * 0.132f, -0.04f - row * 0.036f, -0.012f);
                StyleButton(btn, labels[i]);
                b[i] = btn.GetComponent<PressableButton>();
            }
            var panel = go.AddComponent<ShotsPanel>();
            panel.origin = origin;
            panel.shotRenderer = shot;
            panel.tool = tool;
            panel.locomotion = locomotion;
            panel.font = font;
            panel.backgroundMaterial = UnlitMaterial("PanelBlack", Color.black);
            (panel.prev, panel.next, panel.watch, panel.ride) = (b[0], b[1], b[2], b[3]);
            (panel.edit, panel.rename, panel.delete, panel.close) = (b[4], b[5], b[6], b[7]);

            var keyboardPrefab = AssetDatabase.LoadAssetAtPath<GameObject>(KeyboardPrefab);
            if (keyboardPrefab != null)
            {
                var kb = (GameObject)PrefabUtility.InstantiatePrefab(keyboardPrefab, scene);
                kb.name = "Rename Keyboard";
                panel.keyboard = kb.GetComponentInChildren<MixedReality.Toolkit.UX.Experimental.NonNativeKeyboard>(true);
            }
            else Debug.LogWarning($"[VR Director] No keyboard prefab at {KeyboardPrefab}; Rename disabled.");
            return panel;
        }

        /// <summary>The help panel (open at start) with its own Close button.</summary>
        static HelpPanel AddHelpPanel(Scene scene, XROrigin origin, TMP_FontAsset font, GameObject buttonPrefab)
        {
            var go = new GameObject("Help Panel");
            SceneManager.MoveGameObjectToScene(go, scene);
            var close = (GameObject)PrefabUtility.InstantiatePrefab(buttonPrefab, go.transform);
            close.name = "Close";
            close.transform.localPosition = new Vector3(HelpPanel.Width / 2 - 0.08f, HelpPanel.Height / 2 - 0.035f, -0.012f);
            StyleButton(close, "Close");
            var help = go.AddComponent<HelpPanel>();
            help.origin = origin;
            help.font = font;
            help.backgroundMaterial = UnlitMaterial("PanelBlack", Color.black);
            help.closeButton = close.GetComponent<PressableButton>();
            return help;
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

        /// <summary>
        /// Label text, bigger than MRTK's default (0.06) so it reads at arm's length, on a
        /// solid black backing (MRTK's plates are see-through, unreadable over a bright room).
        /// </summary>
        static void StyleButton(GameObject button, string label)
        {
            PathMenu.SetLabel(button.transform, label);
            foreach (var t in button.GetComponentsInChildren<TMP_Text>(true))
                if (!t.gameObject.name.Contains("Icon")) t.fontSize = 0.085f;
            AddBacking(button.transform, new Vector2(0.128f, 0.032f), 0.006f);
        }

        /// <summary>A black quad behind <paramref name="parent"/>'s content (z = depth behind it).</summary>
        static void AddBacking(Transform parent, Vector2 size, float depth)
        {
            var quad = GameObject.CreatePrimitive(PrimitiveType.Quad);
            quad.name = "Black Backing";
            Object.DestroyImmediate(quad.GetComponent<Collider>());
            quad.transform.SetParent(parent, false);
            quad.transform.localPosition = new Vector3(0, 0, depth);
            quad.transform.localScale = new Vector3(size.x, size.y, 1);
            quad.GetComponent<Renderer>().sharedMaterial = UnlitMaterial("PanelBlack", Color.black);
            quad.layer = parent.gameObject.layer;
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
