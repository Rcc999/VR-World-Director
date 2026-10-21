using System.Collections.Generic;
using MixedReality.Toolkit.UX;
using MixedReality.Toolkit.UX.Experimental;
using TMPro;
using Unity.XR.CoreUtils;
using UnityEngine;

namespace VRDirector
{
    /// <summary>
    /// The shots of this scene (<see cref="ShotLibrary"/>), one at a time:
    /// &lt; Prev / Next &gt; to browse, Watch (on a screen), Ride (immersive), Edit (back
    /// to the start with that shot's cameras; Generate then makes a new shot and keeps
    /// this one), Rename (touch keyboard), Delete (press twice), Close.
    /// </summary>
    public class ShotsPanel : MonoBehaviour
    {
        public XROrigin origin;
        public ShotRenderer shotRenderer;
        public CameraPathTool tool;
        public VRLocomotion locomotion;
        public TMP_FontAsset font;
        public Material backgroundMaterial;
        public NonNativeKeyboard keyboard;
        public PressableButton prev, next, watch, ride, edit, rename, delete, close;

        public const float Width = 0.56f, Height = 0.34f;

        public bool IsOpen => gameObject.activeSelf;

        List<ShotLibrary.Shot> shots = new();
        int index;
        TextMeshPro info;
        float deleteArmedAt = -10f;

        ShotLibrary.Shot Current => index >= 0 && index < shots.Count ? shots[index] : null;

        void Awake()
        {
            if (origin == null) origin = FindFirstObjectByType<XROrigin>();
            var bg = GameObject.CreatePrimitive(PrimitiveType.Quad);
            bg.name = "Background";
            Destroy(bg.GetComponent<Collider>());
            bg.transform.SetParent(transform, false);
            bg.transform.localScale = new Vector3(Width, Height, 1);
            bg.GetComponent<Renderer>().sharedMaterial = backgroundMaterial;

            info = new GameObject("Info").AddComponent<TextMeshPro>();
            info.transform.SetParent(transform, false);
            info.transform.localPosition = new Vector3(0, 0.08f, -0.005f);
            info.font = font;
            info.fontSize = 0.35f;
            info.alignment = TextAlignmentOptions.Center;
            info.rectTransform.sizeDelta = new Vector2(Width - 0.04f, 0.16f);

            prev.OnClicked.AddListener(() => Select(index - 1));
            next.OnClicked.AddListener(() => Select(index + 1));
            watch.OnClicked.AddListener(() => { var s = Current; Close(); shotRenderer.Watch(s); });
            ride.OnClicked.AddListener(() => { var s = Current; Close(); shotRenderer.Ride(s); });
            edit.OnClicked.AddListener(Edit);
            rename.OnClicked.AddListener(Rename);
            delete.OnClicked.AddListener(Delete);
            close.OnClicked.AddListener(Close);
            gameObject.SetActive(false);
        }

        public void Open()
        {
            shots = ShotLibrary.List();
            index = shots.Count - 1; // newest first
            var head = origin.Camera.transform;
            Vector3 fwd = Vector3.ProjectOnPlane(head.forward, Vector3.up).normalized;
            if (fwd.sqrMagnitude < 1e-4f) fwd = Vector3.forward;
            transform.SetPositionAndRotation(head.position + fwd * 0.55f - 0.15f * Vector3.up, // arm's reach
                                             Quaternion.LookRotation(fwd, Vector3.up));
            gameObject.SetActive(true);
            Refresh();
        }

        public void Close()
        {
            if (keyboard != null && keyboard.gameObject.activeSelf) keyboard.Close();
            gameObject.SetActive(false);
        }

        public void Toggle()
        {
            if (IsOpen) Close(); else Open();
        }

        void Select(int i)
        {
            if (shots.Count == 0) return;
            index = (i % shots.Count + shots.Count) % shots.Count; // wrap around
            Refresh();
        }

        void Refresh()
        {
            var s = Current;
            info.text = s == null
                ? "<b>No shots yet</b>\nPlace cameras, then Generate."
                : $"<b>{s.data.name}</b>   ({index + 1}/{shots.Count})\n" +
                  $"{s.data.keyframes?.Length ?? 0} cameras  -  {s.Seconds:F1} s  -  {s.data.speed}\n{s.data.created}";
            foreach (var b in new[] { prev, next, watch, ride, edit, rename, delete })
                b.enabled = s != null;
        }

        /// <summary>Back to the start of the scene with this shot's cameras, ready to change.</summary>
        void Edit()
        {
            var s = Current;
            if (s == null) return;
            tool.SetCameras(s.data.keyframes);
            locomotion.ResetToSpawn();
            Close();
        }

        void Rename()
        {
            var s = Current;
            if (s == null || keyboard == null) return;
            var head = origin.Camera.transform;
            Vector3 fwd = Vector3.ProjectOnPlane(head.forward, Vector3.up).normalized;
            keyboard.transform.SetPositionAndRotation(head.position + fwd * 0.5f - 0.3f * Vector3.up,
                                                      Quaternion.LookRotation(fwd, Vector3.up));
            keyboard.OnTextSubmit.RemoveAllListeners();
            keyboard.OnTextSubmit.AddListener(text => { ShotLibrary.Rename(s, text); Refresh(); });
            keyboard.SubmitOnEnter = true;
            keyboard.Open(s.data.name);
        }

        /// <summary>First press arms it ("Confirm delete"), a second press within 3 s deletes.</summary>
        void Delete()
        {
            var s = Current;
            if (s == null) return;
            if (Time.time - deleteArmedAt > 3f) { deleteArmedAt = Time.time; return; }
            deleteArmedAt = -10f;
            ShotLibrary.Delete(s);
            shots.RemoveAt(index);
            index = Mathf.Min(index, shots.Count - 1);
            Refresh();
        }

        void Update() => PathMenu.SetLabel(delete, Time.time - deleteArmedAt < 3f ? "Confirm delete" : "Delete");
    }
}
