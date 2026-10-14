// Colored point cloud for URP, drawn as view-facing squares.
// Each point is baked into 4 vertices sharing one position; TEXCOORD0 holds the
// corner (-1..1), and the vertex shader pushes it out in view space. No geometry
// shader, so it runs on Metal (Mac editor) and Vulkan/GLES (Android XR), and it
// supports single-pass instanced / multiview stereo.
//
// Point size: clouds from a Gaussian splat carry a per-point diameter
// (TEXCOORD0.z, meters) taken from the splat's footprint. Clouds without it
// (single depth map) grow with distance from the capture camera, so
// neighboring pixels of the depth map still touch: spacing ~ depth / focal_px.
Shader "VRDirector/PointCloud"
{
    Properties
    {
        _SizeScale ("Size multiplier for per-point sizes", Float) = 1
        _SizePerMeter ("Point size per meter from capture camera", Float) = 0.003
        _MinSize ("Minimum point size (m)", Float) = 0.002
        _CaptureOrigin ("Capture camera position (object space)", Vector) = (0, 1.5, 0, 0)
    }
    SubShader
    {
        Tags { "RenderType" = "Opaque" "RenderPipeline" = "UniversalPipeline" "Queue" = "Geometry" }

        Pass
        {
            Name "PointCloud"
            Tags { "LightMode" = "UniversalForward" }
            Cull Off
            ZWrite On

            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_instancing

            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.core/ShaderLibrary/Color.hlsl"

            CBUFFER_START(UnityPerMaterial)
                float _SizeScale;
                float _SizePerMeter;
                float _MinSize;
                float4 _CaptureOrigin;
            CBUFFER_END

            struct Attributes
            {
                float4 positionOS : POSITION;
                half4 color : COLOR;
                float3 corner : TEXCOORD0; // xy = corner (-1..1), z = diameter (m) or 0
                UNITY_VERTEX_INPUT_INSTANCE_ID
            };

            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                half3 color : COLOR;
                UNITY_VERTEX_OUTPUT_STEREO
            };

            Varyings vert(Attributes v)
            {
                Varyings o = (Varyings)0;
                UNITY_SETUP_INSTANCE_ID(v);
                UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);

                float objectScale = length(GetObjectToWorldMatrix()._m00_m10_m20);
                float dist = length(v.positionOS.xyz - _CaptureOrigin.xyz);
                float size = v.corner.z > 0 ? v.corner.z * _SizeScale
                                            : max(_SizePerMeter * dist, _MinSize);
                float halfSize = 0.5 * objectScale * size;

                float3 positionVS = TransformWorldToView(TransformObjectToWorld(v.positionOS.xyz));
                positionVS.xy += v.corner.xy * halfSize;
                o.positionCS = TransformWViewToHClip(positionVS);

                // PLY colors are sRGB bytes; the project renders in linear space.
                #if UNITY_COLORSPACE_GAMMA
                    o.color = v.color.rgb;
                #else
                    o.color = SRGBToLinear(v.color.rgb);
                #endif
                return o;
            }

            half4 frag(Varyings i) : SV_Target
            {
                return half4(i.color, 1);
            }
            ENDHLSL
        }
    }
}
