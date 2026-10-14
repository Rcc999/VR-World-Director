using System;
using System.IO;
using System.Linq;
using GaussianSplatting.Runtime;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;
using UnityEngine.SceneManagement;

namespace VRDirector.Editor
{
    /// <summary>
    /// Builds Assets/Scenes/SplatViewer.unity: the same XR rig as the point cloud
    /// viewer, with a real Gaussian splat (GaussianSplatRenderer, Unity Gaussian
    /// Splatting package) instead of points.
    ///
    /// Select a GaussianSplatAsset (made with Tools > Gaussian Splats > Create
    /// GaussianSplatAsset from server/splat_for_unity.py's .ply) and run the menu.
    /// The splat keeps COLMAP coordinates; its Transform comes from the
    /// "&lt;name&gt;.transform.json" written next to that .ply, copied into Assets.
    ///
    /// Also applies the project settings the splat renderer needs on Android XR.
    /// </summary>
    public static class SplatSceneBuilder
    {
        const string ViewerScene = "Assets/Scenes/SplatViewer.unity";
        const string PackageRoot = "Packages/org.nesnausk.gaussian-splatting";

        [Serializable]
        class SplatTransform
        {
            public float[] position;
            public float[] rotation; // x, y, z, w
            public float[] scale;
        }

        [MenuItem("VR Director/Build Gaussian Splat Viewer Scene")]
        public static void Build()
        {
            var asset = Selection.activeObject as GaussianSplatAsset;
            if (asset == null)
            {
                EditorUtility.DisplayDialog("VR Director",
                    "Select a GaussianSplatAsset in the Project window first.\n\n" +
                    "Create one with Tools > Gaussian Splats > Create GaussianSplatAsset " +
                    "from the .ply written by server/splat_for_unity.py.", "OK");
                return;
            }
            var placement = FindTransform(asset);
            if (placement == null) return;
            if (!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;

            ConfigureProject();

            var scene = PointCloudSceneBuilder.OpenViewerTemplate();
            var go = new GameObject(asset.name + " (Gaussian Splat)");
            SceneManager.MoveGameObjectToScene(go, scene);
            go.transform.SetPositionAndRotation(
                new Vector3(placement.position[0], placement.position[1], placement.position[2]),
                new Quaternion(placement.rotation[0], placement.rotation[1], placement.rotation[2], placement.rotation[3]));
            go.transform.localScale = new Vector3(placement.scale[0], placement.scale[1], placement.scale[2]);

            var gs = go.AddComponent<GaussianSplatRenderer>();
            gs.m_Asset = asset;
            gs.m_ShaderSplats = Load<Shader>("Shaders/RenderGaussianSplats.shader");
            gs.m_ShaderComposite = Load<Shader>("Shaders/GaussianComposite.shader");
            gs.m_ShaderDebugPoints = Load<Shader>("Shaders/GaussianDebugRenderPoints.shader");
            gs.m_ShaderDebugBoxes = Load<Shader>("Shaders/GaussianDebugRenderBoxes.shader");
            gs.m_CSSplatUtilities = Load<ComputeShader>("Shaders/SplatUtilities.compute");

            PointCloudSceneBuilder.SaveAsOnlyBuildScene(scene, ViewerScene);
            Selection.activeGameObject = go;
            Debug.Log($"[VR Director] {ViewerScene} built with {AssetDatabase.GetAssetPath(asset)} " +
                      $"({asset.splatCount} splats); it is now the only scene enabled for builds.");
        }

        static T Load<T>(string relativePath) where T : UnityEngine.Object
        {
            var obj = AssetDatabase.LoadAssetAtPath<T>($"{PackageRoot}/{relativePath}");
            if (obj == null) Debug.LogError($"[VR Director] Missing {PackageRoot}/{relativePath}");
            return obj;
        }

        /// <summary>"&lt;asset name&gt;.transform.json" anywhere under Assets.</summary>
        static SplatTransform FindTransform(GaussianSplatAsset asset)
        {
            string file = asset.name + ".transform.json";
            string path = Directory.GetFiles("Assets", file, SearchOption.AllDirectories).FirstOrDefault();
            if (path == null)
            {
                EditorUtility.DisplayDialog("VR Director", $"No {file} under Assets.\n\n" +
                    "Copy the .transform.json that server/splat_for_unity.py wrote next to the " +
                    ".ply into Assets (e.g. Assets/GaussianAssets).", "OK");
                return null;
            }
            var t = JsonUtility.FromJson<SplatTransform>(File.ReadAllText(path));
            if (t?.position?.Length != 3 || t.rotation?.Length != 4 || t.scale?.Length != 3)
            {
                EditorUtility.DisplayDialog("VR Director", $"{path} is not a valid transform file.", "OK");
                return null;
            }
            return t;
        }

        /// <summary>
        /// Settings the splat renderer needs: Vulkan only on Android (it uses compute
        /// shaders and wave intrinsics; no OpenGL ES), single-threaded rendering (reported
        /// fix for Android), URP intermediate texture "Always" (with HDR off, "Auto"
        /// renders splats upside down), and the GaussianSplatURPFeature on every
        /// URP renderer. MSAA must stay off (it already is in this project).
        /// </summary>
        static void ConfigureProject()
        {
            PlayerSettings.SetUseDefaultGraphicsAPIs(BuildTarget.Android, false);
            PlayerSettings.SetGraphicsAPIs(BuildTarget.Android, new[] { GraphicsDeviceType.Vulkan });
            PlayerSettings.SetMobileMTRendering(NamedBuildTarget.Android, false);

            var featureType = typeof(GaussianSplatRenderer).Assembly
                .GetType("GaussianSplatting.Runtime.GaussianSplatURPFeature");
            foreach (string guid in AssetDatabase.FindAssets("t:UniversalRendererData", new[] { "Assets" }))
            {
                var data = AssetDatabase.LoadAssetAtPath<UniversalRendererData>(AssetDatabase.GUIDToAssetPath(guid));
                data.intermediateTextureMode = IntermediateTextureMode.Always;
                if (featureType != null && !data.rendererFeatures.Any(f => f != null && f.GetType() == featureType))
                    AddRendererFeature(data, featureType);
                EditorUtility.SetDirty(data);
            }
            if (featureType == null)
                Debug.LogError("[VR Director] GaussianSplatURPFeature not found; add it to the URP renderers by hand.");
            AssetDatabase.SaveAssets();
        }

        /// <summary>Same steps as the renderer Inspector's "Add Renderer Feature" button.</summary>
        static void AddRendererFeature(ScriptableRendererData data, Type featureType)
        {
            var feature = (ScriptableRendererFeature)ScriptableObject.CreateInstance(featureType);
            feature.name = featureType.Name;
            AssetDatabase.AddObjectToAsset(feature, data);
            AssetDatabase.TryGetGUIDAndLocalFileIdentifier(feature, out _, out long localId);

            var so = new SerializedObject(data);
            var features = so.FindProperty("m_RendererFeatures");
            var map = so.FindProperty("m_RendererFeatureMap");
            features.arraySize++;
            features.GetArrayElementAtIndex(features.arraySize - 1).objectReferenceValue = feature;
            map.arraySize++;
            map.GetArrayElementAtIndex(map.arraySize - 1).longValue = localId;
            so.ApplyModifiedProperties();
            Debug.Log($"[VR Director] Added {featureType.Name} to {AssetDatabase.GetAssetPath(data)}");
        }
    }
}
