using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace VRDirector.Editor
{
    /// <summary>
    /// Puffin worlds as textured depth meshes (server/puffin_fusion/depth_mesh.py):
    /// Assets/Meshes/Puffin/&lt;Name&gt;/ holds one .obj + .png per Puffin view, already in
    /// Unity coordinates. Menu VR Director → Build Puffin Mesh Worlds makes one scene per
    /// folder, Scenes/Puffin/Puffin-&lt;Name&gt;.unity, each view drawn unlit with its image
    /// (no lighting: the colors are already the generated pixels) and from both sides.
    /// </summary>
    public static class PuffinMeshSceneBuilder
    {
        public const string MeshRoot = "Assets/Meshes/Puffin";
        const string PuffinScenes = "Assets/Scenes/Puffin";

        [MenuItem("VR Director/Build Puffin Mesh Worlds")]
        public static void Build()
        {
            var folders = Directory.Exists(MeshRoot)
                ? Directory.GetDirectories(MeshRoot).OrderBy(p => p).ToArray()
                : new string[0];
            if (folders.Length == 0)
            {
                EditorUtility.DisplayDialog("VR Director", $"No mesh folders in {MeshRoot}.\n" +
                    "Run server/puffin_fusion/depth_mesh.py with --out there.", "OK");
                return;
            }
            if (!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
            var shader = Shader.Find("Universal Render Pipeline/Unlit");
            Directory.CreateDirectory(PuffinScenes);

            foreach (string folder in folders.Select(f => f.Replace('\\', '/')))
            {
                string name = Path.GetFileName(folder);
                var objs = Directory.GetFiles(folder, "*.obj").OrderBy(p => p).ToArray();
                if (objs.Length == 0) continue;

                var scene = PointCloudSceneBuilder.OpenViewerTemplate();
                var world = new GameObject(name);
                EditorSceneManager.MoveGameObjectToScene(world, scene);
                foreach (string objPath in objs.Select(p => p.Replace('\\', '/')))
                {
                    var model = AssetDatabase.LoadAssetAtPath<GameObject>(objPath);
                    var tex = AssetDatabase.LoadAssetAtPath<Texture2D>(Path.ChangeExtension(objPath, ".png"));
                    if (model == null || tex == null) { Debug.LogError($"[VR Director] Missing mesh or texture for {objPath}"); continue; }

                    string matPath = Path.ChangeExtension(objPath, ".mat");
                    var mat = AssetDatabase.LoadAssetAtPath<Material>(matPath);
                    if (mat == null) { mat = new Material(shader); AssetDatabase.CreateAsset(mat, matPath); }
                    mat.shader = shader;
                    mat.SetTexture("_BaseMap", tex);
                    mat.SetFloat("_Cull", 0f); // both sides: the importer flips winding
                    EditorUtility.SetDirty(mat);

                    var view = (GameObject)PrefabUtility.InstantiatePrefab(model, scene);
                    view.transform.SetParent(world.transform, false);
                    foreach (var r in view.GetComponentsInChildren<MeshRenderer>())
                    {
                        r.sharedMaterial = mat;
                        r.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
                        r.receiveShadows = false;
                    }
                }
                CameraToolsBuilder.MarkAsScene(world);
                string path = $"{PuffinScenes}/Puffin-{name}.unity";
                EditorSceneManager.SaveScene(scene, path);
                Debug.Log($"[VR Director] {path} built from {objs.Length} views in {folder}.");
            }
            AssetDatabase.SaveAssets();
            PointCloudSceneBuilder.EnableWorldScenes();
        }
    }

    /// <summary>Import settings for the depth meshes: 32-bit indices, no materials, sharp textures.</summary>
    class PuffinMeshImport : AssetPostprocessor
    {
        bool Ours => assetPath.StartsWith(PuffinMeshSceneBuilder.MeshRoot + "/");

        void OnPreprocessModel()
        {
            if (!Ours) return;
            var m = (ModelImporter)assetImporter;
            m.materialImportMode = ModelImporterMaterialImportMode.None;
            m.indexFormat = ModelImporterIndexFormat.UInt32;
            m.meshCompression = ModelImporterMeshCompression.Off;
            m.importNormals = ModelImporterNormals.None;
            m.importAnimation = false;
            m.isReadable = false;
        }

        void OnPreprocessTexture()
        {
            if (!Ours) return;
            var t = (TextureImporter)assetImporter;
            t.wrapMode = TextureWrapMode.Clamp;
            t.maxTextureSize = 4096;
            t.mipmapEnabled = true;
            t.anisoLevel = 4;
            t.textureCompression = TextureImporterCompression.CompressedHQ;
        }
    }
}
