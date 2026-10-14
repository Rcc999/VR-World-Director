using Unity.XR.CoreUtils;
using UnityEngine;
using UnityEngine.InputSystem;

namespace VRDirector
{
    /// <summary>
    /// Moves the XR rig through a scene that is bigger than the play space.
    ///
    /// Hands (Galaxy XR without controllers): hold a left-hand pinch to glide
    /// forward where you look, a right-hand pinch to glide backward, and hold both
    /// pinches for a moment to return to the spawn point. Turn by turning your body.
    /// Controllers, if present: left stick walks (relative to where you look),
    /// right stick left/right snap-turns, B / Y returns to the spawn point.
    ///
    /// Movement stays horizontal: the rig keeps its height, so the floor stays
    /// under your real floor.
    /// </summary>
    [RequireComponent(typeof(XROrigin))]
    public class VRLocomotion : MonoBehaviour
    {
        [Tooltip("Walking speed in m/s.")]
        public float speed = 1.0f;

        [Tooltip("Degrees per snap turn.")]
        public float snapTurnDegrees = 30f;

        [Tooltip("Pinch strength (0..1) that counts as a held pinch.")]
        public float pinchThreshold = 0.8f;

        [Tooltip("Seconds both pinches must be held to return to the spawn point.")]
        public float resetHoldSeconds = 1.5f;

        XROrigin origin;
        Pose spawn;
        bool turnReady = true;
        float bothPinchedFor;
        InputAction move, turn, pinchForward, pinchBack, reset;

        void Awake()
        {
            origin = GetComponent<XROrigin>();
            spawn = new Pose(transform.position, transform.rotation);

            move = new InputAction("Move", InputActionType.Value, "<XRController>{LeftHand}/{Primary2DAxis}");
            turn = new InputAction("Turn", InputActionType.Value, "<XRController>{RightHand}/{Primary2DAxis}");
            pinchForward = new InputAction("Pinch Forward", InputActionType.Value, "<HandInteraction>{LeftHand}/pinchValue");
            pinchBack = new InputAction("Pinch Back", InputActionType.Value, "<HandInteraction>{RightHand}/pinchValue");
            reset = new InputAction("Reset", InputActionType.Button);
            reset.AddBinding("<XRController>{RightHand}/{SecondaryButton}");
            reset.AddBinding("<XRController>{LeftHand}/{SecondaryButton}");
        }

        void OnEnable()
        {
            foreach (var a in new[] { move, turn, pinchForward, pinchBack, reset }) a.Enable();
        }

        void OnDisable()
        {
            foreach (var a in new[] { move, turn, pinchForward, pinchBack, reset }) a.Disable();
        }

        void Update()
        {
            var head = origin.Camera != null ? origin.Camera.transform : transform;
            Vector3 up = transform.up;
            Vector3 forward = Vector3.ProjectOnPlane(head.forward, up).normalized;
            Vector3 right = Vector3.Cross(up, forward);

            Vector2 stick = move.ReadValue<Vector2>();
            bool pinchingLeft = pinchForward.ReadValue<float>() >= pinchThreshold;
            bool pinchingRight = pinchBack.ReadValue<float>() >= pinchThreshold;
            float glide = (pinchingLeft ? 1f : 0f) - (pinchingRight ? 1f : 0f); // both pinched: stand still
            Vector3 direction = forward * (stick.y + glide) + right * stick.x;
            if (direction.sqrMagnitude > 1f) direction.Normalize();
            transform.position += direction * (speed * Time.deltaTime);

            // Snap turn once per stick flick; the stick must come back to center.
            float x = turn.ReadValue<Vector2>().x;
            if (turnReady && Mathf.Abs(x) > 0.7f)
            {
                origin.RotateAroundCameraUsingOriginUp(Mathf.Sign(x) * snapTurnDegrees);
                turnReady = false;
            }
            else if (Mathf.Abs(x) < 0.3f)
            {
                turnReady = true;
            }

            bothPinchedFor = pinchingLeft && pinchingRight ? bothPinchedFor + Time.deltaTime : 0f;
            if (reset.WasPressedThisFrame() || bothPinchedFor >= resetHoldSeconds)
            {
                transform.SetPositionAndRotation(spawn.position, spawn.rotation);
                bothPinchedFor = float.NegativeInfinity; // once per hold
            }
        }
    }
}
