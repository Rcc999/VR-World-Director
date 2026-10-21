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
//
// Color mode (globals set by WorldState, so every cloud follows the menu):
// 0 = the cloud's own colors, 1 = height above the floor (y), 2 = distance to the
// viewer. Modes 1-2 use turbo colors like the server's depth videos (red = near / high).
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

            // Globals (Shader.SetGlobalFloat), not per material: 0 when unset = own colors.
            float _VRDColorMode;
            float _VRDHeightMax;
            float _VRDDepthMax;

            // Turbo colormap, polynomial fit (Mikhailov 2019), t in 0..1, sRGB out.
            half3 Turbo(float t)
            {
                const float4 kR4 = float4(0.13572138, 4.61539260, -42.66032258, 132.13108234);
                const float4 kG4 = float4(0.09140261, 2.19418839, 4.84296658, -14.18503333);
                const float4 kB4 = float4(0.10667330, 12.64194608, -60.58204836, 110.36276771);
                const float2 kR2 = float2(-152.94239396, 59.28637943);
                const float2 kG2 = float2(4.27729857, 2.82956604);
                const float2 kB2 = float2(-89.90310912, 27.34824973);
                t = saturate(t);
                float4 v4 = float4(1.0, t, t * t, t * t * t);
                float2 v2 = v4.zw * v4.z;
                return half3(dot(v4, kR4) + dot(v2, kR2), dot(v4, kG4) + dot(v2, kG2), dot(v4, kB4) + dot(v2, kB2));
            }

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

                float3 positionWS = TransformObjectToWorld(v.positionOS.xyz);
                float3 positionVS = TransformWorldToView(positionWS);
                positionVS.xy += v.corner.xy * halfSize;
                o.positionCS = TransformWViewToHClip(positionVS);

                half3 color = v.color.rgb;
                if (_VRDColorMode > 0.5 && _VRDColorMode < 1.5)
                    color = Turbo(positionWS.y / max(_VRDHeightMax, 0.01));
                else if (_VRDColorMode > 1.5)
                    color = Turbo(1 - length(positionWS - GetCameraPositionWS()) / max(_VRDDepthMax, 0.01));

                // PLY colors are sRGB bytes; the project renders in linear space.
                #if UNITY_COLORSPACE_GAMMA
                    o.color = color;
                #else
                    o.color = SRGBToLinear(color);
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
