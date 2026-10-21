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
    /// Reset position | Speed (Slow / Medium / Fast), Generate, Shots (browse, watch,
    /// ride, edit, rename, delete; "Stop" while one plays), Help, Worlds (scene picker).
    /// </summary>
    public class PathMenu : MonoBehaviour
    {
        public CameraPathTool tool;
        public ShotRenderer shot;
        public VRLocomotion locomotion;
        public HelpPanel help;
        public ShotsPanel shots;
        public WorldsPanel worlds;
        public PressableButton newCamera, undo, clear, save, resetPosition, speed, generate, shotsButton, helpButton, worldsButton;

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
            generate.OnClicked.AddListener(() => { CloseAll(); shot.Generate(); });
            shotsButton.OnClicked.AddListener(() =>
            {
                if (shot.IsWatching || shot.IsRiding) shot.Stop();
                else { help.Close(); CloseWorlds(); shots.Toggle(); }
            });
            helpButton.OnClicked.AddListener(() => { shots.Close(); CloseWorlds(); help.Toggle(); });
            if (worldsButton != null && worlds != null)
                worldsButton.OnClicked.AddListener(() => { help.Close(); shots.Close(); worlds.Toggle(); });
            resetPosition.OnClicked.AddListener(() => locomotion.ResetToSpawn());
        }

        void Update()
        {
            SetLabel(newCamera, tool.IsHolding ? "Cancel camera" : "New camera");
            SetLabel(save, Time.time - savedAt < 2f ? "Saved" : "Save");
            SetLabel(speed, $"Speed: {shot.speed}");
            SetLabel(generate, shot.IsBusy ? "Rendering..." : "Generate");
            SetLabel(shotsButton, shot.IsWatching ? "Stop video" : shot.IsRiding ? "Stop ride"
                                  : shots.IsOpen ? "Close shots" : "Shots");
            SetLabel(helpButton, help.IsOpen ? "Close help" : "Help");
            if (worldsButton != null && worlds != null) SetLabel(worldsButton, worlds.IsOpen ? "Close worlds" : "Worlds");
        }

        void CloseWorlds()
        {
            if (worlds != null) worlds.Close();
        }

        void CloseAll()
        {
            help.Close();
            shots.Close();
            CloseWorlds();
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
