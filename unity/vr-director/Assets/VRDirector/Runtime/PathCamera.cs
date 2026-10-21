using MixedReality.Toolkit;
using MixedReality.Toolkit.SpatialManipulation;
using TMPro;
using UnityEngine;

namespace VRDirector
{
    /// <summary>
    /// One camera keyframe of the shot: a small camera model with its number, a view
    /// cone, and a live preview screen on its back (a second Unity camera rendering
    /// the scene into a texture). Pinch it to move and rotate it. Its horizon stays
    /// level: the camera can pan and tilt but never roll.
    /// </summary>
    public class PathCamera : MonoBehaviour
    {
        public const float VerticalFov = 60f, Aspect = 16f / 9f;
        static readonly Color Idle = new(0.85f, 0.9f, 1f), Active = new(1f, 0.8f, 0.2f);

        public ObjectManipulator Manipulator { get; private set; }
        public bool IsGrabbed => Manipulator != null && Manipulator.isSelected;

        Camera previewCam;
        RenderTexture previewRT;
        TextMeshPro label;
        Renderer body;
        bool previewForced;

        public static PathCamera Create(Transform parent, Material bodyMat, Material lineMat, Material screenMat,
                                        TMP_FontAsset font, Vector2Int previewSize)
        {
            var go = new GameObject("Path Camera");
            go.transform.SetParent(parent, false);
            var cam = go.AddComponent<PathCamera>();
            cam.Build(bodyMat, lineMat, screenMat, font, previewSize);
            return cam;
        }

        void Build(Material bodyMat, Material lineMat, Material screenMat, TMP_FontAsset font, Vector2Int previewSize)
        {
            // Body (keeps its BoxCollider: that is what you pinch) and lens.
            var bodyGo = GameObject.CreatePrimitive(PrimitiveType.Cube);
            bodyGo.name = "Body";
            bodyGo.transform.SetParent(transform, false);
            bodyGo.transform.localScale = new Vector3(0.10f, 0.065f, 0.05f);
            body = bodyGo.GetComponent<Renderer>();
            body.material = new Material(bodyMat);

            var lens = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
            lens.name = "Lens";
            Destroy(lens.GetComponent<Collider>());
            lens.transform.SetParent(transform, false);
            lens.transform.localPosition = new Vector3(0, 0, 0.04f);
            lens.transform.localRotation = Quaternion.Euler(90, 0, 0);
            lens.transform.localScale = new Vector3(0.04f, 0.015f, 0.04f);
            lens.GetComponent<Renderer>().sharedMaterial = body.sharedMaterial;

            // Preview: camera in front of the lens -> texture on a screen on the back.
            previewRT = new RenderTexture(previewSize.x, previewSize.y, 24) { name = "Path Camera Preview" };
            var camGo = new GameObject("Preview Camera");
            camGo.transform.SetParent(transform, false);
            camGo.transform.localPosition = new Vector3(0, 0, 0.06f);
            previewCam = camGo.AddComponent<Camera>();
            previewCam.stereoTargetEye = StereoTargetEyeMask.None; // render to the texture, not the headset
            previewCam.targetTexture = previewRT;
            previewCam.fieldOfView = VerticalFov;
            previewCam.aspect = Aspect;
            previewCam.nearClipPlane = 0.02f;
            previewCam.farClipPlane = 1000f; // Puffin worlds reach ~150 m (sky shell)
            previewCam.clearFlags = CameraClearFlags.SolidColor;
            previewCam.backgroundColor = Color.black;
            previewCam.cullingMask = SceneLayers.SceneMask; // the room only, like the final shot
            previewCam.enabled = false;

            var screen = GameObject.CreatePrimitive(PrimitiveType.Quad);
            screen.name = "Preview Screen";
            Destroy(screen.GetComponent<Collider>());
            screen.transform.SetParent(transform, false);
            screen.transform.localPosition = new Vector3(0, 0, -0.026f);
            screen.transform.localRotation = Quaternion.Euler(0, 180, 0); // faces the person holding it
            screen.transform.localScale = new Vector3(0.09f, 0.09f / Aspect, 1);
            var screenRenderer = screen.GetComponent<Renderer>();
            screenRenderer.material = new Material(screenMat) { mainTexture = previewRT };

            // View cone: where the shot looks.
            var cone = new GameObject("View Cone").AddComponent<LineRenderer>();
            cone.transform.SetParent(transform, false);
            cone.useWorldSpace = false;
            cone.widthMultiplier = 0.003f;
            cone.sharedMaterial = lineMat;
            float d = 0.35f, h = d * Mathf.Tan(VerticalFov * 0.5f * Mathf.Deg2Rad), w = h * Aspect;
            Vector3 apex = new(0, 0, 0.05f), c1 = new(-w, h, d), c2 = new(w, h, d), c3 = new(w, -h, d), c4 = new(-w, -h, d);
            var pts = new[] { c1, c2, c3, c4, c1, apex, c2, c3, apex, c4 };
            for (int i = 0; i < pts.Length; i++) if (pts[i] != apex) pts[i] += apex;
            cone.positionCount = pts.Length;
            cone.SetPositions(pts);

            // Number above the camera.
            label = new GameObject("Number").AddComponent<TextMeshPro>();
            label.transform.SetParent(transform, false);
            label.transform.localPosition = new Vector3(0, 0.07f, 0);
            label.font = font;
            label.fontSize = 0.6f;
            label.alignment = TextAlignmentOptions.Center;
            label.rectTransform.sizeDelta = new Vector2(0.2f, 0.08f);

            // Pinch to grab: move + rotate, no scaling.
            Manipulator = gameObject.AddComponent<ObjectManipulator>();
            Manipulator.AllowedManipulations = TransformFlags.Move | TransformFlags.Rotate;
        }

        public void SetNumber(int n) => label.text = n.ToString();

        /// <summary>Keep the preview running while held (it otherwise runs only while grabbed).</summary>
        public void SetPreview(bool on) => previewForced = on;

        public void SetGrabbable(bool on) => Manipulator.enabled = on;

        void LateUpdate()
        {
            transform.rotation = Level(transform.rotation);

            bool active = previewForced || IsGrabbed;
            previewCam.enabled = active;
            body.material.color = active ? Active : Idle;

            var head = Camera.main;
            if (head != null)
            {
                Vector3 toHead = Vector3.ProjectOnPlane(head.transform.position - label.transform.position, Vector3.up);
                if (toHead.sqrMagnitude > 1e-6f) label.transform.rotation = Quaternion.LookRotation(-toHead, Vector3.up);
            }
        }

        /// <summary>Same viewing direction, roll removed (horizon level).</summary>
        public static Quaternion Level(Quaternion q)
        {
            Vector3 f = q * Vector3.forward;
            return Mathf.Abs(f.y) > 0.999f ? q : Quaternion.LookRotation(f, Vector3.up);
        }

        void OnDestroy()
        {
            if (previewCam != null) previewCam.targetTexture = null;
            if (previewRT != null) previewRT.Release();
        }
    }
}
