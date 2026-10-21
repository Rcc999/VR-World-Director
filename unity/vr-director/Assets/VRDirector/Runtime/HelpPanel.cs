using System.Collections;
using MixedReality.Toolkit.UX;
using TMPro;
using Unity.XR.CoreUtils;
using UnityEngine;

namespace VRDirector
{
    /// <summary>
    /// A panel listing every gesture and menu button. It opens in front of you when
    /// the app starts; close it with its Close button, reopen it with Help in the menu.
    /// </summary>
    public class HelpPanel : MonoBehaviour
    {
        public XROrigin origin;
        public TMP_FontAsset font;
        public Material backgroundMaterial;
        public PressableButton closeButton;

        public const float Width = 0.76f, Height = 0.78f;

        const string Text =
            "<b>VR Director - how to use</b>\n\n" +
            "<b>Move</b>  pinch in empty space and pull\n" +
            "<b>Turn</b>  pinch with both hands and rotate them\n" +
            "<b>Menu</b>  turn your LEFT palm toward you, press with your RIGHT index\n\n" +
            "<b>New camera</b>  appears in your right hand, its view on its back:\n" +
            "      aim, then pinch to place it (numbered 1, 2, 3...)\n" +
            "<b>Edit a camera</b>  pinch it, move or rotate your hand\n" +
            "<b>Undo / Clear all</b>  remove the last / all cameras\n" +
            "<b>Save</b>  keep the cameras for next time\n" +
            "<b>Speed</b>  Slow / Medium / Fast along the path\n" +
            "<b>Generate</b>  render a new shot along cameras 1 > 2 > 3... (shot1, shot2...)\n" +
            "<b>Shots</b>  browse your shots: Watch (screen), Ride (you move along it),\n" +
            "      Edit (its cameras come back, Generate makes a new shot), Rename, Delete\n" +
            "<b>Reset position</b>  back to the start\n" +
            "<b>Worlds</b>  switch scene (3DGS room, Puffin worlds); each keeps its own cameras and shots";

        public bool IsOpen => gameObject.activeSelf;

        void Awake()
        {
            if (origin == null) origin = FindFirstObjectByType<XROrigin>();
            var bg = GameObject.CreatePrimitive(PrimitiveType.Quad);
            bg.name = "Background";
            Destroy(bg.GetComponent<Collider>());
            bg.transform.SetParent(transform, false);
            bg.transform.localScale = new Vector3(Width, Height, 1);
            bg.GetComponent<Renderer>().sharedMaterial = backgroundMaterial;

            var text = new GameObject("Text").AddComponent<TextMeshPro>();
            text.transform.SetParent(transform, false);
            text.transform.localPosition = new Vector3(0, -0.02f, -0.005f); // below the Close button
            text.font = font;
            text.fontSize = 0.22f;
            text.alignment = TextAlignmentOptions.TopLeft;
            text.rectTransform.sizeDelta = new Vector2(Width - 0.06f, Height - 0.12f);
            text.text = Text;

            if (closeButton != null) closeButton.OnClicked.AddListener(Close);
        }

        IEnumerator Start()
        {
            gameObject.SetActive(true);
            yield return null; // wait one frame so the head pose is tracked
            Open();
        }

        public void Open()
        {
            // Within arm's reach (0.6 m), a bit below the eyes, facing you.
            var head = origin.Camera.transform;
            Vector3 fwd = Vector3.ProjectOnPlane(head.forward, Vector3.up).normalized;
            if (fwd.sqrMagnitude < 1e-4f) fwd = Vector3.forward;
            transform.SetPositionAndRotation(head.position + fwd * 0.6f - 0.1f * Vector3.up,
                                             Quaternion.LookRotation(fwd, Vector3.up));
            gameObject.SetActive(true);
        }

        public void Close() => gameObject.SetActive(false);

        public void Toggle()
        {
            if (IsOpen) Close(); else Open();
        }
    }
}
