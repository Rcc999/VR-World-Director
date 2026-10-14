using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEditor.AssetImporters;
using UnityEngine;
using UnityEngine.Rendering;

namespace VRDirector.Editor
{
    /// <summary>
    /// Imports binary little-endian .ply point clouds (x, y, z + red, green, blue,
    /// optional per-point diameter `size` in meters)
    /// as a GameObject with a quad-per-point mesh drawn by VRDirector/PointCloud.
    /// Coordinates are taken as-is: the Python side already writes Unity axes
    /// (y up, left-handed, meters).
    /// </summary>
    [ScriptedImporter(2, "ply")]
    public class PlyImporter : ScriptedImporter
    {
        [Tooltip("Randomly keep at most this many points (0 = keep all). Lower it if the headset drops frames.")]
        public int maxPoints = 0;

        [Tooltip("Multiplier on per-point sizes (clouds from splat_to_points.py). Raise it if surfaces show gaps.")]
        public float sizeScale = 1f;

        [Tooltip("Point size per meter of distance from the capture camera (clouds without per-point sizes).")]
        public float sizePerMeter = 0.003f;

        [Tooltip("Capture camera position in the cloud's coordinates (photo position).")]
        public Vector3 captureOrigin = new Vector3(0f, 1.5f, 0f);

        public override void OnImportAsset(AssetImportContext ctx)
        {
            ReadPly(ctx.assetPath, out var positions, out var colors, out var sizes);
            Subsample(ref positions, ref colors, ref sizes, maxPoints);

            var mesh = BuildQuadMesh(positions, colors, sizes);
            mesh.name = Path.GetFileNameWithoutExtension(ctx.assetPath);

            ctx.DependsOnSourceAsset(ShaderPath);
            var shader = AssetDatabase.LoadAssetAtPath<Shader>(ShaderPath);
            if (shader == null)
            {
                ctx.LogImportError($"Point cloud shader not found at {ShaderPath}");
                return;
            }
            var material = new Material(shader) { name = mesh.name + " (Point Cloud)" };
            material.SetFloat("_SizeScale", sizeScale);
            material.SetFloat("_SizePerMeter", sizePerMeter);
            material.SetVector("_CaptureOrigin", captureOrigin);

            var go = new GameObject(mesh.name);
            go.AddComponent<MeshFilter>().sharedMesh = mesh;
            var renderer = go.AddComponent<MeshRenderer>();
            renderer.sharedMaterial = material;
            renderer.shadowCastingMode = ShadowCastingMode.Off;
            renderer.receiveShadows = false;
            renderer.lightProbeUsage = LightProbeUsage.Off;
            renderer.reflectionProbeUsage = ReflectionProbeUsage.Off;

            ctx.AddObjectToAsset("root", go);
            ctx.AddObjectToAsset("mesh", mesh);
            ctx.AddObjectToAsset("material", material);
            ctx.SetMainObject(go);
        }

        const string ShaderPath = "Assets/VRDirector/Shaders/PointCloud.shader";

        static Mesh BuildQuadMesh(Vector3[] positions, Color32[] colors, float[] sizes)
        {
            int n = positions.Length;
            var vertices = new Vector3[n * 4];
            var vertexColors = new Color32[n * 4];
            var corners = new Vector3[n * 4]; // xy = corner, z = diameter (0 = shader default)
            var indices = new int[n * 6];
            var cornerOffsets = new[]
            {
                new Vector2(-1, -1), new Vector2(1, -1), new Vector2(1, 1), new Vector2(-1, 1)
            };
            for (int i = 0; i < n; i++)
            {
                int v = i * 4;
                for (int k = 0; k < 4; k++)
                {
                    vertices[v + k] = positions[i];
                    vertexColors[v + k] = colors[i];
                    corners[v + k] = new Vector3(cornerOffsets[k].x, cornerOffsets[k].y, sizes[i]);
                }
                int t = i * 6;
                indices[t] = v; indices[t + 1] = v + 1; indices[t + 2] = v + 2;
                indices[t + 3] = v; indices[t + 4] = v + 2; indices[t + 5] = v + 3;
            }

            var mesh = new Mesh { indexFormat = IndexFormat.UInt32 };
            mesh.SetVertices(vertices);
            mesh.SetColors(vertexColors);
            mesh.SetUVs(0, corners);
            mesh.SetIndices(indices, MeshTopology.Triangles, 0, calculateBounds: false);
            var bounds = new Bounds(positions.Length > 0 ? positions[0] : Vector3.zero, Vector3.zero);
            foreach (var p in positions) bounds.Encapsulate(p);
            bounds.Expand(0.2f); // room for the quads' extent
            mesh.bounds = bounds;
            mesh.UploadMeshData(markNoLongerReadable: true);
            return mesh;
        }

        static void Subsample(ref Vector3[] positions, ref Color32[] colors, ref float[] sizes, int max)
        {
            if (max <= 0 || positions.Length <= max) return;
            var rng = new System.Random(0);
            var order = new int[positions.Length];
            for (int i = 0; i < order.Length; i++) order[i] = i;
            for (int i = 0; i < max; i++) // partial Fisher-Yates
            {
                int j = rng.Next(i, order.Length);
                (order[i], order[j]) = (order[j], order[i]);
            }
            var p = new Vector3[max];
            var c = new Color32[max];
            var s = new float[max];
            for (int i = 0; i < max; i++)
            {
                p[i] = positions[order[i]]; c[i] = colors[order[i]]; s[i] = sizes[order[i]];
            }
            positions = p;
            colors = c;
            sizes = s;
        }

        // --- PLY parsing -------------------------------------------------------

        struct Property { public string name; public string type; public int offset; }

        static int TypeSize(string type) => type switch
        {
            "char" or "int8" or "uchar" or "uint8" => 1,
            "short" or "int16" or "ushort" or "uint16" => 2,
            "int" or "int32" or "uint" or "uint32" or "float" or "float32" => 4,
            "double" or "float64" => 8,
            _ => throw new FormatException($"unsupported PLY property type '{type}'"),
        };

        static double ReadValue(byte[] data, int at, string type) => type switch
        {
            "float" or "float32" => BitConverter.ToSingle(data, at),
            "double" or "float64" => BitConverter.ToDouble(data, at),
            "uchar" or "uint8" => data[at],
            "char" or "int8" => (sbyte)data[at],
            "short" or "int16" => BitConverter.ToInt16(data, at),
            "ushort" or "uint16" => BitConverter.ToUInt16(data, at),
            "int" or "int32" => BitConverter.ToInt32(data, at),
            "uint" or "uint32" => BitConverter.ToUInt32(data, at),
            _ => throw new FormatException(type),
        };

        static void ReadPly(string path, out Vector3[] positions, out Color32[] colors, out float[] sizes)
        {
            byte[] data = File.ReadAllBytes(path);

            // Header: ASCII lines up to "end_header". The vertex element must come
            // first, so its records start right after the header.
            int headerEnd = 0, vertexCount = -1, stride = 0;
            string element = null;
            var props = new List<Property>();
            while (true)
            {
                int eol = Array.IndexOf(data, (byte)'\n', headerEnd);
                if (eol < 0) throw new FormatException("PLY header has no end_header");
                var parts = Encoding.ASCII.GetString(data, headerEnd, eol - headerEnd)
                    .Split(' ', StringSplitOptions.RemoveEmptyEntries);
                headerEnd = eol + 1;
                if (parts.Length == 0) continue;
                if (parts[0] == "end_header") break;
                if (parts[0] == "format" && parts[1] != "binary_little_endian")
                    throw new FormatException($"only binary_little_endian PLY is supported, got {parts[1]}");
                if (parts[0] == "element")
                {
                    element = parts[1];
                    if (element == "vertex") vertexCount = int.Parse(parts[2]);
                    else if (vertexCount < 0) throw new FormatException("vertex must be the first PLY element");
                }
                else if (parts[0] == "property" && element == "vertex")
                {
                    if (parts[1] == "list") throw new FormatException("list properties on vertices are not supported");
                    props.Add(new Property { name = parts[2], type = parts[1], offset = stride });
                    stride += TypeSize(parts[1]);
                }
            }
            if (vertexCount < 0) throw new FormatException("PLY has no vertex element");

            Property Find(string name)
            {
                int i = props.FindIndex(p => p.name == name);
                if (i < 0) throw new FormatException($"PLY has no vertex property '{name}'");
                return props[i];
            }
            var px = Find("x"); var py = Find("y"); var pz = Find("z");
            bool hasColor = props.Exists(p => p.name == "red");
            var pr = hasColor ? Find("red") : default;
            var pg = hasColor ? Find("green") : default;
            var pb = hasColor ? Find("blue") : default;
            bool hasSize = props.Exists(p => p.name == "size");
            var ps = hasSize ? Find("size") : default;

            if (headerEnd + (long)vertexCount * stride > data.Length)
                throw new FormatException("PLY file is shorter than its header says");

            positions = new Vector3[vertexCount];
            colors = new Color32[vertexCount];
            sizes = new float[vertexCount];
            for (int i = 0; i < vertexCount; i++)
            {
                int b = headerEnd + i * stride;
                positions[i] = new Vector3(
                    (float)ReadValue(data, b + px.offset, px.type),
                    (float)ReadValue(data, b + py.offset, py.type),
                    (float)ReadValue(data, b + pz.offset, pz.type));
                colors[i] = hasColor
                    ? new Color32(
                        (byte)ReadValue(data, b + pr.offset, pr.type),
                        (byte)ReadValue(data, b + pg.offset, pg.type),
                        (byte)ReadValue(data, b + pb.offset, pb.type), 255)
                    : new Color32(255, 255, 255, 255);
                if (hasSize) sizes[i] = (float)ReadValue(data, b + ps.offset, ps.type);
            }
        }
    }
}
