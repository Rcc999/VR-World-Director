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
    /// ride, edit, rename, delete; "Stop" while one plays), Help, Worlds (scene picker)
    /// and World state (world state scenes only).
    /// </summary>
    public class PathMenu : MonoBehaviour
    {
        public CameraPathTool tool;
        public ShotRenderer shot;
        public VRLocomotion locomotion;
        public HelpPanel help;
        public ShotsPanel shots;
        public WorldsPanel worlds;
        [Tooltip("Optional: only in scenes built with Build World State Scene.")]
        public WorldStatePanel worldState;
        public PressableButton newCamera, undo, clear, save, resetPosition, speed, generate, shotsButton, helpButton,
                               worldsButton, worldStateButton;

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
                else { CloseAll(except: shots); shots.Toggle(); }
            });
            helpButton.OnClicked.AddListener(() => { CloseAll(except: help); help.Toggle(); });
            if (worldsButton != null && worlds != null)
                worldsButton.OnClicked.AddListener(() => { CloseAll(except: worlds); worlds.Toggle(); });
            if (worldStateButton != null && worldState != null)
                worldStateButton.OnClicked.AddListener(() => { CloseAll(except: worldState); worldState.Toggle(); });
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
            if (worldStateButton != null && worldState != null)
                SetLabel(worldStateButton, worldState.IsOpen ? "Close state" : "World state");
        }

        /// <summary>Closes every panel but <paramref name="except"/> (so a button toggles its own).</summary>
        void CloseAll(Component except = null)
        {
            if (except != help) help.Close();
            if (except != shots) shots.Close();
            if (worlds != null && except != worlds) worlds.Close();
            if (worldState != null && except != worldState) worldState.Close();
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
