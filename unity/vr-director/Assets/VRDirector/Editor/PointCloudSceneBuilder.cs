using System.Linq;
using UnityEditor;
using Unity.XR.CoreUtils;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace VRDirector.Editor
{
    /// <summary>
    /// Builds Assets/Scenes/PointCloudViewer.unity from the working HelloCube scene
    /// (same MRTK XR rig and XR setup): removes the cube, drops in the selected
    /// .ply point cloud at the origin, and makes the viewer the scene that gets built.
    /// The cloud's floor is at y=0 and its capture position at x=z=0, so the XR rig at
    /// the origin (floor tracking) puts you where the photo / video was taken.
    /// The rig gets <see cref="VRLocomotion"/>, and the scene is made fully immersive:
    /// AR Session off and an opaque black background instead of passthrough.
    /// </summary>
    public static class PointCloudSceneBuilder
    {
        const string TemplateScene = "Assets/HelloCube.unity";
        const string ViewerScene = "Assets/Scenes/PointCloudViewer.unity";
        const string DefaultCloud = "Assets/PointClouds/Depth/test-room0.ply";
        static readonly string[] PassthroughComponents = { "ARCameraManager", "ARCameraBackground", "CameraSettingsManager" };

        [MenuItem("VR Director/Build Point Cloud Viewer Scene")]
        public static void Build()
        {
            string cloudPath = Selection.activeObject != null
                && AssetDatabase.GetAssetPath(Selection.activeObject).EndsWith(".ply")
                    ? AssetDatabase.GetAssetPath(Selection.activeObject)
                    : DefaultCloud;
            var cloud = AssetDatabase.LoadAssetAtPath<GameObject>(cloudPath);
            if (cloud == null)
            {
                EditorUtility.DisplayDialog("VR Director", $"No point cloud at {cloudPath}.\n" +
                    "Select a .ply in the Project window, or import one there.", "OK");
                return;
            }
            if (!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;

            var scene = OpenViewerTemplate();
            var instance = (GameObject)PrefabUtility.InstantiatePrefab(cloud, scene);
            instance.transform.SetPositionAndRotation(Vector3.zero, Quaternion.identity);
            CameraToolsBuilder.MarkAsScene(instance);

            SaveAsOnlyBuildScene(scene, ViewerScene);
            Selection.activeGameObject = instance;
            Debug.Log($"[VR Director] {ViewerScene} built with {cloudPath}; it is now the only scene enabled for builds.");
        }

        /// <summary>
        /// Opens the HelloCube template without its cube, with the XR rig at the
        /// origin (floor tracking, locomotion, opaque black background), the
        /// AR Session off, and the camera keyframe tools + left-palm menu.
        /// </summary>
        internal static Scene OpenViewerTemplate()
        {
            var scene = EditorSceneManager.OpenScene(TemplateScene, OpenSceneMode.Single);
            foreach (var root in scene.GetRootGameObjects().Where(g => g.name == "Cube"))
                Object.DestroyImmediate(root);

            var origin = Object.FindFirstObjectByType<XROrigin>();
            if (origin != null)
            {
                origin.transform.SetPositionAndRotation(Vector3.zero, Quaternion.identity);
                origin.RequestedTrackingOriginMode = XROrigin.TrackingOriginMode.Floor;
                if (origin.GetComponent<VRLocomotion>() == null)
                    origin.gameObject.AddComponent<VRLocomotion>();
                if (origin.Camera != null)
                {
                    origin.Camera.clearFlags = CameraClearFlags.SolidColor;
                    origin.Camera.backgroundColor = Color.black; // alpha 1: no passthrough
                }
                // ARCameraManager turns on camera passthrough on Android XR, and MRTK's
                // CameraSettingsManager overwrites the clear color at startup.
                foreach (var b in origin.GetComponentsInChildren<Behaviour>(true)
                             .Where(b => b != null && PassthroughComponents.Contains(b.GetType().Name)))
                    b.enabled = false;
            }
            else
            {
                Debug.LogWarning("[VR Director] No XROrigin in the template scene; locomotion not added.");
            }
            foreach (var root in scene.GetRootGameObjects().Where(g => g.name == "AR Session"))
                root.SetActive(false);
            CameraToolsBuilder.Add(scene, origin);
            return scene;
        }

        /// <summary>Saves the scene and makes it the only scene enabled for builds.</summary>
        internal static void SaveAsOnlyBuildScene(Scene scene, string path)
        {
            EditorSceneManager.SaveScene(scene, path);
            EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene(path, true) }
                .Concat(EditorBuildSettings.scenes
                    .Where(s => s.path != path)
                    .Select(s => new EditorBuildSettingsScene(s.path, false)))
                .ToArray();
        }
    }
}
