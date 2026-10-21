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
            // Floating over the left palm, a few cm off it so the right index can press
            // without touching the hand.
            foreach (var hc in menuGo.GetComponentsInChildren<HandConstraint>(true))
            {
                hc.SafeZone = HandConstraint.SolverSafeZone.AtopPalm;
                hc.SafeZoneBuffer = 0.05f;
            }
            // Two headed columns (CAMERAS | SHOTS), then a divider and the scene / general
            // buttons: Worlds | World state (world state scenes only, AddWorldMenu), Reset | Help.
            string[] labels = { "New camera", "Undo", "Clear all", "Save", "Reset position",
                                "Speed: Medium", "Generate", "Shots", "Help", "Worlds" };
            (int col, int row)[] slots = { (0, 0), (0, 1), (0, 2), (0, 3), (0, 5), (1, 0), (1, 1), (1, 2), (1, 5), (0, 4) };
            backplate.localScale = new Vector3(MenuWidth, MenuHeight, 0.02f);

            var buttons = new PressableButton[labels.Length];
            // MRTK's backplate material is rebound at runtime, so add our own black backing too.
            AddBacking(content, new Vector2(MenuWidth + 0.006f, MenuHeight + 0.006f), 0.012f);
            for (int i = 0; i < labels.Length; i++)
            {
                var b = (GameObject)PrefabUtility.InstantiatePrefab(buttonPrefab, collection);
                b.name = labels[i];
                b.transform.localPosition = MenuSlot(slots[i].col, slots[i].row);
                buttons[i] = b.GetComponent<PressableButton>();
                StyleButton(b, labels[i]);
            }
            AddHeader(collection, "CAMERAS", new Vector3(-MenuColumn / 2, MenuHeaderY, -0.012f), font);
            AddHeader(collection, "SHOTS", new Vector3(MenuColumn / 2, MenuHeaderY, -0.012f), font);
            AddDivider(collection, new Vector3(0, (MenuSlot(0, 3).y + MenuSlot(0, 4).y) / 2, -0.012f), MenuWidth - 0.02f);

            // UI layer: the menu stays visible while you ride a shot (headset then shows Scene + UI).
            SceneLayers.SetLayerRecursively(menuGo, LayerMask.NameToLayer("UI"));
            var menu = menuGo.AddComponent<PathMenu>();
            menu.tool = tool;
            menu.shot = shot;
            shot.menu = menuGo;
            menu.locomotion = locomotion;
            (menu.newCamera, menu.undo, menu.clear, menu.save, menu.resetPosition) =
                (buttons[0], buttons[1], buttons[2], buttons[3], buttons[4]);
            (menu.speed, menu.generate, menu.shotsButton, menu.helpButton, menu.worldsButton) =
                (buttons[5], buttons[6], buttons[7], buttons[8], buttons[9]);
            menu.help = AddHelpPanel(scene, origin, font, buttonPrefab);
            menu.shots = AddShotsPanel(scene, origin, font, buttonPrefab, tool, shot, locomotion);
            menu.worlds = AddWorldsPanel(scene, origin, font, buttonPrefab, shot);
        }

        /// <summary>The scene picker: up to 12 world buttons (labels and layout set at runtime from the build list) + Close.</summary>
        static WorldsPanel AddWorldsPanel(Scene scene, XROrigin origin, TMP_FontAsset font, GameObject buttonPrefab,
                                          ShotRenderer shot)
        {
            var go = new GameObject("Worlds Panel");
            SceneManager.MoveGameObjectToScene(go, scene);
            var worldButtons = new PressableButton[12];
            for (int i = 0; i <= worldButtons.Length; i++)
            {
                bool isClose = i == worldButtons.Length;
                var btn = (GameObject)PrefabUtility.InstantiatePrefab(buttonPrefab, go.transform);
                btn.name = isClose ? "Close" : $"World {i + 1}";
                btn.transform.localPosition = new Vector3(0, WorldsPanel.Top - i * WorldsPanel.Step, -0.012f);
                StyleButton(btn, isClose ? "Close" : btn.name);
                if (isClose) go.AddComponent<WorldsPanel>().close = btn.GetComponent<PressableButton>();
                else worldButtons[i] = btn.GetComponent<PressableButton>();
            }
            var panel = go.GetComponent<WorldsPanel>();
            panel.worldButtons = worldButtons;
            panel.origin = origin;
            panel.shotRenderer = shot;
            panel.font = font;
            panel.backgroundMaterial = UnlitMaterial("PanelBlack", Color.black);
            return panel;
        }

        // Hand menu grid: 128x32 mm buttons with 12 mm gaps (16 mm between columns); rows 0-3
        // under the column headers, rows 4-5 below a divider. Centered on the menu.
        const float MenuStep = 0.044f, MenuColumn = 0.144f, DividerGap = 0.016f;
        const float MenuWidth = 2 * MenuColumn + 0.012f, MenuHeight = 0.308f;
        const float MenuTop = 0.104f; // row 0
        const float MenuHeaderY = MenuTop + 0.034f;

        internal static Vector3 MenuSlot(int col, int row) => new(
            (col - 0.5f) * MenuColumn,
            MenuTop - row * MenuStep - (row >= 4 ? DividerGap : 0),
            -0.012f);

        /// <summary>A small grey caption, e.g. a column or row title.</summary>
        static void AddHeader(Transform parent, string text, Vector3 position, TMP_FontAsset font,
                              float size = 0.07f, TextAlignmentOptions align = TextAlignmentOptions.Center, float width = 0.26f)
        {
            var t = new GameObject($"Header {text}").AddComponent<TextMeshPro>();
            t.transform.SetParent(parent, false);
            t.transform.localPosition = position;
            t.font = font;
            t.fontSize = size;
            t.fontStyle = FontStyles.Bold;
            t.characterSpacing = 4;
            t.color = new Color(0.65f, 0.75f, 0.85f);
            t.alignment = align;
            t.rectTransform.sizeDelta = new Vector2(width, 0.02f);
            t.gameObject.layer = parent.gameObject.layer;
        }

        static void AddDivider(Transform parent, Vector3 position, float width)
        {
            var quad = GameObject.CreatePrimitive(PrimitiveType.Quad);
            quad.name = "Divider";
            Object.DestroyImmediate(quad.GetComponent<Collider>());
            quad.transform.SetParent(parent, false);
            quad.transform.localPosition = position;
            quad.transform.localScale = new Vector3(width, 0.0015f, 1);
            quad.GetComponent<Renderer>().sharedMaterial = UnlitMaterial("Divider", new Color(0.35f, 0.4f, 0.45f));
            quad.layer = parent.gameObject.layer;
        }

        /// <summary>
        /// World state scenes: a World state button in the menu's free slot (next to Worlds,
        /// below the divider) and the <see cref="WorldStatePanel"/> it opens. Call after <see cref="Add"/>.
        /// </summary>
        internal static void AddWorldMenu(Scene scene, XROrigin origin, WorldState world)
        {
            var menu = scene.GetRootGameObjects().SelectMany(g => g.GetComponentsInChildren<PathMenu>(true)).FirstOrDefault();
            var buttonPrefab = AssetDatabase.LoadAssetAtPath<GameObject>(ButtonPrefab);
            if (menu == null || buttonPrefab == null)
            {
                Debug.LogError("[VR Director] No hand menu in the scene; World menu not added.");
                return;
            }
            var font = AssetDatabase.LoadAssetAtPath<TMP_FontAsset>(FontAsset);
            world.lineMaterial = UnlitMaterial("PathLine", new Color(0.3f, 0.85f, 1f));
            world.screenMaterial = UnlitMaterial("CameraScreen", Color.white);
            world.font = font;

            var collection = menu.GetComponentsInChildren<Transform>(true).First(t => t.name == "ButtonCollection");
            var b = (GameObject)PrefabUtility.InstantiatePrefab(buttonPrefab, collection);
            b.name = "World state";
            b.transform.localPosition = MenuSlot(1, 4);
            StyleButton(b, "World state");
            SceneLayers.SetLayerRecursively(b, menu.gameObject.layer);
            menu.worldStateButton = b.GetComponent<PressableButton>();

            var go = new GameObject("World Panel");
            SceneManager.MoveGameObjectToScene(go, scene);
            // Close in the corner; SCENE row (3 toggles); REPLAY row (< run, play, run >, video).
            // Switching scenes is the Worlds panel's job.
            const float w = WorldStatePanel.Width;
            (string label, Vector3 pos)[] layout =
            {
                ("Generated: On", new Vector3(-MenuColumn, WorldStatePanel.SceneRowY, -0.012f)),
                ("Color: Photo", new Vector3(0, WorldStatePanel.SceneRowY, -0.012f)),
                ("Gravity: Off", new Vector3(MenuColumn, WorldStatePanel.SceneRowY, -0.012f)),
                ("< Run", new Vector3(-1.5f * MenuColumn, WorldStatePanel.ReplayRowY, -0.012f)),
                ("Play", new Vector3(-0.5f * MenuColumn, WorldStatePanel.ReplayRowY, -0.012f)),
                ("Run >", new Vector3(0.5f * MenuColumn, WorldStatePanel.ReplayRowY, -0.012f)),
                ("Video: RGB", new Vector3(1.5f * MenuColumn, WorldStatePanel.ReplayRowY, -0.012f)),
                ("Close", new Vector3(w / 2 - 0.08f, WorldStatePanel.Height / 2 - 0.035f, -0.012f)),
            };
            var bs = new PressableButton[layout.Length];
            for (int i = 0; i < layout.Length; i++)
            {
                var btn = (GameObject)PrefabUtility.InstantiatePrefab(buttonPrefab, go.transform);
                btn.name = layout[i].label;
                btn.transform.localPosition = layout[i].pos;
                StyleButton(btn, layout[i].label);
                bs[i] = btn.GetComponent<PressableButton>();
            }
            float headerX = -w / 2 + 0.03f + 0.25f; // left edge of a 0.5 m wide caption
            AddHeader(go.transform, "SCENE  -  what is around you", new Vector3(headerX, WorldStatePanel.SceneRowY + 0.036f, -0.012f),
                      font, align: TextAlignmentOptions.Left, width: 0.5f);
            AddHeader(go.transform, "REPLAY  -  the camera runs Puffin generated", new Vector3(headerX, WorldStatePanel.ReplayRowY + 0.036f, -0.012f),
                      font, align: TextAlignmentOptions.Left, width: 0.5f);
            var panel = go.AddComponent<WorldStatePanel>();
            panel.origin = origin;
            panel.world = world;
            panel.font = font;
            panel.backgroundMaterial = UnlitMaterial("PanelBlack", Color.black);
            (panel.generated, panel.colors, panel.gravity) = (bs[0], bs[1], bs[2]);
            (panel.prevRun, panel.replay, panel.nextRun, panel.layer, panel.close) = (bs[3], bs[4], bs[5], bs[6], bs[7]);
            menu.worldState = panel;
        }

        const string KeyboardPrefab ="Packages/org.mixedrealitytoolkit.uxcomponents/Experimental/NonNativeKeyboard/TouchableNonNativeKeyboard.prefab";

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
