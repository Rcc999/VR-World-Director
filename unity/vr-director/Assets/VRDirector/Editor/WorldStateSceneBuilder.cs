using System.Collections.Generic;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;
using Unity.XR.CoreUtils;
using UnityEditor;
using UnityEngine;
using UnityEngine.Video;

namespace VRDirector.Editor
{
    /// <summary>
    /// Menu <b>VR Director → Build World State Scene</b>: builds
    /// Assets/Scenes/WorldStates/&lt;scene&gt;.unity from a world state folder
    /// (Assets/WorldStates/&lt;scene&gt;/, made by server/world_state/to_unity.py):
    /// the real cloud and the generated cloud as separate objects, a
    /// <see cref="WorldState"/> baked from world_state/world_state.json (runs, poses,
    /// roll / pitch, caption, physics check, the run videos), and the World button +
    /// panel on the hand menu. Same XR rig and tools as the point cloud viewer; cameras
    /// are saved per scene. <b>Build All World State Scenes</b> does every folder. The built
    /// scene starts the app and every built world state scene is in the build, so
    /// &lt; Scene / Scene &gt; in the World panel switches between them.
    /// </summary>
    public static class WorldStateSceneBuilder
    {
        const string Root = "Assets/WorldStates";
        const int MaxPointsPerCloud = 1000000; // headset budget per cloud

        [MenuItem("VR Director/Build World State Scene")]
        public static void Build()
        {
            string folder = SelectedSceneFolder();
            if (folder == null)
            {
                EditorUtility.DisplayDialog("VR Director",
                    $"Select a world state folder in {Root}/ (or a file inside it) in the Project window.\n" +
                    "Make one with server/world_state/to_unity.py.", "OK");
                return;
            }
            Build(folder);
        }

        [MenuItem("VR Director/Build All World State Scenes")]
        public static void BuildAll()
        {
            var folders = Directory.GetDirectories(Root).Select(d => d.Replace('\\', '/'))
                .Where(d => File.Exists($"{d}/world_state/world_state.json")).OrderBy(d => d).ToArray();
            if (folders.Length == 0) { Debug.LogError($"[VR Director] No world states in {Root}"); return; }
            if (!EditorSceneManagerSave()) return;
            var built = folders.Select(BuildScene).Where(p => p != null).ToList();
            if (built.Count > 0) SetBuildScenes(built[0]);
        }

        /// <summary>Builds one folder, e.g. "Assets/WorldStates/ruin", and makes it the start scene (also for -executeMethod).</summary>
        public static void Build(string folder)
        {
            if (!EditorSceneManagerSave()) return;
            var path = BuildScene(folder);
            if (path != null) SetBuildScenes(path);
        }

        /// <summary>
        /// Build settings: <paramref name="first"/> starts the app, then every other world state
        /// scene (enabled, for the scene buttons); all other scenes stay listed but disabled.
        /// </summary>
        static void SetBuildScenes(string first)
        {
            var worlds = Directory.Exists(WorldState.ScenesFolder)
                ? Directory.GetFiles(WorldState.ScenesFolder, "*.unity").Select(f => f.Replace('\\', '/')).OrderBy(f => f).ToList()
                : new List<string>();
            worlds.Remove(first);
            worlds.Insert(0, first);
            EditorBuildSettings.scenes = worlds.Select(p => new EditorBuildSettingsScene(p, true))
                .Concat(EditorBuildSettings.scenes.Where(s => !worlds.Contains(s.path) && File.Exists(s.path))
                                                  .Select(s => new EditorBuildSettingsScene(s.path, false)))
                .ToArray();
            Debug.Log($"[VR Director] Build scenes: {string.Join(", ", worlds)} (starts with {Path.GetFileNameWithoutExtension(first)}).");
        }

        static string BuildScene(string folder)
        {
            string jsonPath = $"{folder}/world_state/world_state.json";
            if (!File.Exists(jsonPath)) { Debug.LogError($"[VR Director] No {jsonPath}"); return null; }

            var scene = PointCloudSceneBuilder.OpenViewerTemplate();
            var real = Instantiate(folder, File.Exists($"{folder}/real.ply") ? "real.ply" : null, scene);
            var generated = Instantiate(folder, File.Exists($"{folder}/generated.ply") ? "generated.ply" : null, scene);
            if (real == null && generated == null) { Debug.LogError($"[VR Director] No clouds in {folder}"); return null; }

            var go = new GameObject("World State");
            UnityEngine.SceneManagement.SceneManager.MoveGameObjectToScene(go, scene);
            var world = go.AddComponent<WorldState>();
            world.realCloud = real;
            world.generatedCloud = generated;
            world.origin = Object.FindFirstObjectByType<XROrigin>();
            Bake(world, JObject.Parse(File.ReadAllText(jsonPath)), folder);
            CameraToolsBuilder.AddWorldMenu(scene, world.origin, world);
            var tool = Object.FindFirstObjectByType<CameraPathTool>();
            if (tool != null) tool.saveName = $"camera_path_{world.sceneName}"; // cameras per world

            Directory.CreateDirectory(WorldState.ScenesFolder);
            string path = $"{WorldState.ScenesFolder}{world.sceneName}.unity";
            UnityEditor.SceneManagement.EditorSceneManager.SaveScene(scene, path);
            Selection.activeGameObject = go;
            Debug.Log($"[VR Director] {path} built with {folder}: real={real?.name ?? "-"}, " +
                      $"generated={generated?.name ?? "-"}, {world.runs.Length} runs.");
            return path;
        }

        static bool EditorSceneManagerSave() => UnityEditor.SceneManagement.EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo();

        static string SelectedSceneFolder()
        {
            var path = Selection.activeObject != null ? AssetDatabase.GetAssetPath(Selection.activeObject) : null;
            if (string.IsNullOrEmpty(path) || !path.StartsWith(Root + "/")) return null;
            var parts = path.Substring(Root.Length + 1).Split('/');
            return $"{Root}/{parts[0]}";
        }

        static GameObject Instantiate(string folder, string file, UnityEngine.SceneManagement.Scene scene)
        {
            if (file == null) return null;
            string path = $"{folder}/{file}";
            // Big clouds (a multi-photo generated.ply has millions of points) get the headset budget.
            if (AssetImporter.GetAtPath(path) is PlyImporter importer && importer.maxPoints == 0)
            {
                importer.maxPoints = MaxPointsPerCloud;
                importer.SaveAndReimport();
            }
            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(path);
            if (prefab == null) { Debug.LogError($"[VR Director] Could not import {path}"); return null; }
            var instance = (GameObject)PrefabUtility.InstantiatePrefab(prefab, scene);
            instance.name = Path.GetFileNameWithoutExtension(file) == "generated" ? "Generated" : "Real";
            instance.transform.SetPositionAndRotation(Vector3.zero, Quaternion.identity);
            CameraToolsBuilder.MarkAsScene(instance);
            return instance;
        }

        static void Bake(WorldState world, JObject json, string folder)
        {
            world.sceneName = Path.GetFileName(folder);
            world.kind = (string)json["kind"] ?? "";
            world.caption = (string)json["caption"] ?? "";
            var g = json["gravity_unity"] as JArray;
            if (g != null && g.Count == 3) world.gravity = new Vector3((float)g[0], (float)g[1], (float)g[2]);
            world.physicsCheck = PhysicsCheck(json["physics_check"] as JObject);

            var runs = new List<WorldState.Run>();
            foreach (var (name, token) in ((JObject)json["runs"] ?? new JObject()).Properties().Select(p => (p.Name, p.Value)))
            {
                var r = (JObject)token;
                var files = r["files"] as JObject ?? new JObject();
                VideoClip Clip(string kind)
                {
                    var f = (string)files[kind];
                    return f == null ? null : AssetDatabase.LoadAssetAtPath<VideoClip>($"{folder}/world_state/{f}");
                }
                runs.Add(new WorldState.Run
                {
                    name = name,
                    generated = (bool?)r["generated"] ?? false,
                    vfov = (float?)r["vfov"] ?? 50f,
                    rgb = Clip("rgb"), depth = Clip("depth"), pfUp = Clip("pf_up"), pfLat = Clip("pf_lat"),
                    views = ((JArray)r["views"] ?? new JArray()).Select(v => View((JObject)v)).ToArray(),
                });
                if (runs[^1].rgb == null) Debug.LogWarning($"[VR Director] {world.sceneName}/{name}: RGB video not found");
            }
            world.runs = runs.ToArray();
        }

        /// <summary>c2w_unity: columns are the camera right / up / forward axes and position.</summary>
        static WorldState.View View(JObject v)
        {
            var m = (JArray)v["c2w_unity"];
            float M(int r, int c) => (float)m[r][c];
            var up = new Vector3(M(0, 1), M(1, 1), M(2, 1));
            var forward = new Vector3(M(0, 2), M(1, 2), M(2, 2));
            return new WorldState.View
            {
                position = new Vector3(M(0, 3), M(1, 3), M(2, 3)),
                rotation = Quaternion.LookRotation(forward, up),
                scene = Angles(v["scene"]), conditioned = Angles(v["conditioned"]), measured = Angles(v["measured"]),
            };
        }

        static WorldState.Angles Angles(JToken t) => t is JObject o
            ? new WorldState.Angles { valid = true, roll = (float?)o["roll"] ?? 0, pitch = (float?)o["pitch"] ?? 0 }
            : new WorldState.Angles();

        /// <summary>One line per check: how well Puffin respected the physics it was told (generated), or matched the real cameras.</summary>
        static string PhysicsCheck(JObject check)
        {
            if (check == null) return "Physics check: not measured yet";
            var lines = new List<string>();
            foreach (var (label, key) in new[] { ("generated vs told", "generated"), ("real vs cameras", "real") })
                if (check[key] is JObject c)
                    lines.Add($"Physics {label}: roll {(float)c["roll_err_deg_median"]:0.0} / pitch {(float)c["pitch_err_deg_median"]:0.0} deg " +
                              $"median error ({(int)c["views"]} views)");
            return lines.Count > 0 ? string.Join("\n", lines) : "Physics check: not measured yet";
        }
    }
}
