using System.Linq;
using MixedReality.Toolkit;
using MixedReality.Toolkit.SpatialManipulation;
using MixedReality.Toolkit.UX;
using TMPro;
using UnityEngine;

namespace VRDirector
{
    /// <summary>
    /// The MRTK hand menu on the left palm (turn the palm toward you; poke the buttons
    /// with the right index finger): New camera / Cancel, Undo, Clear all, Save,
    /// Speed (Slow / Medium / Fast), Generate / Close video, Reset position.
    /// </summary>
    public class PathMenu : MonoBehaviour
    {
        public CameraPathTool tool;
        public ShotRenderer shot;
        public VRLocomotion locomotion;
        public PressableButton newCamera, undo, clear, save, speed, generate, resetPosition;

        float savedAt = -10f;

        void Awake()
        {
            // Left palm only, so the right hand stays free to press buttons and hold cameras.
            foreach (var s in GetComponentsInChildren<SolverHandler>(true))
                s.TrackedHandedness = Handedness.Left;

            newCamera.OnClicked.AddListener(() =>
            {
                if (tool.IsHolding) tool.CancelHeld(); else tool.NewCamera();
            });
            undo.OnClicked.AddListener(tool.Undo);
            clear.OnClicked.AddListener(tool.Clear);
            save.OnClicked.AddListener(() => { tool.Save(); savedAt = Time.time; });
            speed.OnClicked.AddListener(shot.CycleSpeed);
            generate.OnClicked.AddListener(() =>
            {
                if (shot.IsBusy) return;
                if (shot.ScreenVisible) shot.HideScreen(); else shot.Generate();
            });
            resetPosition.OnClicked.AddListener(() => locomotion.ResetToSpawn());
        }

        void Update()
        {
            SetLabel(newCamera, tool.IsHolding ? "Cancel camera" : "New camera");
            SetLabel(save, Time.time - savedAt < 2f ? "Saved" : "Save");
            SetLabel(speed, $"Speed: {shot.speed}");
            SetLabel(generate, shot.IsBusy ? "Rendering..." : shot.ScreenVisible ? "Close video" : "Generate");
        }

        /// <summary>Sets the text of an MRTK text button (not its icon glyph).</summary>
        public static void SetLabel(Component button, string text)
        {
            var label = button.GetComponentsInChildren<TMP_Text>(true)
                .FirstOrDefault(t => !t.gameObject.name.Contains("Icon"));
            if (label != null && label.text != text) label.text = text;
        }
    }
}
