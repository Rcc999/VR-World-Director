using System.Collections.Generic;
using System.Linq;
using Unity.XR.CoreUtils;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.XR.Interaction.Toolkit.Interactors;

namespace VRDirector
{
    public enum Hand { Left, Right }

    /// <summary>
    /// One tracked hand from the OpenXR Hand Interaction profile (Android XR hand
    /// tracking): pinch strength with press/release edges, pinch point and pointing
    /// ray. Positions are in tracking space (the XR rig's floor-offset frame); use
    /// <see cref="ToWorld"/> to get world coordinates. Call <see cref="Update"/> once
    /// per frame before reading.
    /// </summary>
    public class HandInput
    {
        const float PressAt = 0.8f, ReleaseAt = 0.6f; // hysteresis so a held pinch does not flicker

        readonly InputAction pinch, pinchPos, aimPos, aimRot, tracked;

        public bool IsPinching { get; private set; }
        public bool PinchStarted { get; private set; }
        public bool PinchEnded { get; private set; }
        public bool IsTracked => tracked.ReadValue<float>() > 0.5f;
        public Vector3 PinchPosition => pinchPos.ReadValue<Vector3>();
        public Vector3 AimPosition => aimPos.ReadValue<Vector3>();
        public Quaternion AimRotation => aimRot.ReadValue<Quaternion>();

        public HandInput(Hand hand)
        {
            string device = $"<HandInteraction>{{{hand}Hand}}";
            pinch = new InputAction($"{hand} Pinch", InputActionType.Value, $"{device}/pinchValue");
            pinchPos = new InputAction($"{hand} Pinch Position", InputActionType.Value, $"{device}/pinchPosition");
            aimPos = new InputAction($"{hand} Aim Position", InputActionType.Value, $"{device}/pointerPosition");
            aimRot = new InputAction($"{hand} Aim Rotation", InputActionType.Value, $"{device}/pointerRotation");
            tracked = new InputAction($"{hand} Tracked", InputActionType.Value, $"{device}/isTracked");
        }

        public void Enable() { foreach (var a in Actions) a.Enable(); }
        public void Disable() { foreach (var a in Actions) a.Disable(); }
        IEnumerable<InputAction> Actions => new[] { pinch, pinchPos, aimPos, aimRot, tracked };

        public void Update()
        {
            float v = IsTracked ? pinch.ReadValue<float>() : 0f;
            bool now = IsPinching ? v > ReleaseAt : v >= PressAt;
            PinchStarted = now && !IsPinching;
            PinchEnded = !now && IsPinching;
            IsPinching = now;
        }

        /// <summary>Tracking space -> world, through the rig's floor-offset object.</summary>
        public static Transform TrackingSpace(XROrigin origin) =>
            origin.CameraFloorOffsetObject != null ? origin.CameraFloorOffsetObject.transform : origin.transform;

        public static Vector3 ToWorld(XROrigin origin, Vector3 p) => TrackingSpace(origin).TransformPoint(p);

        /// <summary>
        /// True while this hand's MRTK interactors (ray, poke, grab) touch or point at
        /// something interactable, so a pinch there is meant for that object
        /// (button, camera) and not for moving around.
        /// </summary>
        public static bool IsBusy(IReadOnlyList<XRBaseInteractor> handInteractors) =>
            handInteractors.Any(i => i != null && i.isActiveAndEnabled
                                     && (i.hasSelection || i.interactablesHovered.Count > 0));

        /// <summary>The rig's interactors that belong to one hand.</summary>
        public static List<XRBaseInteractor> InteractorsOf(XROrigin origin, Hand hand)
        {
            var wanted = hand == Hand.Left ? InteractorHandedness.Left : InteractorHandedness.Right;
            string side = hand.ToString();
            return origin.GetComponentsInChildren<XRBaseInteractor>(true)
                .Where(i => i.handedness == wanted
                            || (i.handedness == InteractorHandedness.None && HasAncestorNamed(i.transform, side)))
                .ToList();
        }

        static bool HasAncestorNamed(Transform t, string part)
        {
            for (; t != null; t = t.parent)
                if (t.name.Contains(part)) return true;
            return false;
        }
    }
}
