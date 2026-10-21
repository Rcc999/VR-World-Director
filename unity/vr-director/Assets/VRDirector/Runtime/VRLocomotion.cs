using System.Collections.Generic;
using Unity.XR.CoreUtils;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.XR.Interaction.Toolkit.Interactors;

namespace VRDirector
{
    /// <summary>
    /// Moves the XR rig through a scene that is bigger than the play space, with hands
    /// only (Galaxy XR). A pinch only moves you when it starts in empty space: pinches
    /// on a button or a camera belong to that object.
    ///
    /// - Drag: pinch and pull, like pulling yourself along a rope.
    /// - Turn: pinch with both hands and rotate them around each other.
    ///
    /// Controllers, if present: left stick walks, right stick snap-turns, B / Y resets.
    /// Movement stays horizontal, so the floor stays under your real floor.
    /// </summary>
    [RequireComponent(typeof(XROrigin))]
    public class VRLocomotion : MonoBehaviour
    {
        [Tooltip("World meters moved per meter of hand motion while dragging.")]
        public float dragGain = 1.5f;

        [Tooltip("Hand motion (m) that turns a fresh pinch into a drag.")]
        public float dragStartDistance = 0.03f;

        [Header("Controllers (optional)")]
        public float stickSpeed = 1.0f;
        public float snapTurnDegrees = 30f;

        /// <summary>Hands another tool is using (e.g. holding a camera); they do not move the rig.</summary>
        public readonly HashSet<Hand> blockedHands = new();

        enum Mode { None, Undecided, Drag }

        class HandState
        {
            public HandInput input;
            public List<XRBaseInteractor> interactors;
            public Mode mode;
            public Vector3 startPos, lastPos; // tracking space
        }

        XROrigin origin;
        Pose spawn;
        readonly HandState[] hands = { new(), new() };
        Vector3 lastMid, lastSpan;
        bool twoHanded;
        bool turnReady = true;
        InputAction move, turn, reset;

        void Awake()
        {
            origin = GetComponent<XROrigin>();
            spawn = new Pose(transform.position, transform.rotation);
            for (int h = 0; h < 2; h++)
            {
                hands[h].input = new HandInput((Hand)h);
                hands[h].interactors = HandInput.InteractorsOf(origin, (Hand)h);
            }

            move = new InputAction("Move", InputActionType.Value, "<XRController>{LeftHand}/{Primary2DAxis}");
            turn = new InputAction("Turn", InputActionType.Value, "<XRController>{RightHand}/{Primary2DAxis}");
            reset = new InputAction("Reset", InputActionType.Button);
            reset.AddBinding("<XRController>{RightHand}/{SecondaryButton}");
            reset.AddBinding("<XRController>{LeftHand}/{SecondaryButton}");
        }

        void OnEnable()
        {
            foreach (var h in hands) h.input.Enable();
            move.Enable(); turn.Enable(); reset.Enable();
        }

        void OnDisable()
        {
            foreach (var h in hands) h.input.Disable();
            move.Disable(); turn.Disable(); reset.Disable();
        }

        public void ResetToSpawn() => transform.SetPositionAndRotation(spawn.position, spawn.rotation);

        void Update()
        {
            for (int h = 0; h < 2; h++) UpdateHand(hands[h], (Hand)h);

            bool leftOn = hands[0].mode != Mode.None, rightOn = hands[1].mode != Mode.None;
            if (leftOn && rightOn) TwoHandTurn();
            else
            {
                twoHanded = false;
                foreach (var h in hands) OneHand(h);
            }
            Controllers();
        }

        void UpdateHand(HandState s, Hand hand)
        {
            s.input.Update();
            if (s.input.PinchStarted && !blockedHands.Contains(hand) && !HandInput.IsBusy(s.interactors))
            {
                s.mode = Mode.Undecided;
                s.startPos = s.lastPos = s.input.PinchPosition;
            }
            else if (!s.input.IsPinching)
            {
                s.mode = Mode.None;
            }
        }

        void OneHand(HandState s)
        {
            Vector3 p = s.input.PinchPosition;
            if (s.mode == Mode.Undecided && Vector3.Distance(p, s.startPos) > dragStartDistance)
            {
                s.mode = Mode.Drag; // a small dead zone, so a pinch to press something does not nudge you
                s.lastPos = s.startPos;
            }
            if (s.mode == Mode.Drag)
            {
                // Hand in tracking space moved by d: move the rig the other way, so the
                // world appears to follow the hand.
                Vector3 d = HandInput.TrackingSpace(origin).TransformVector(p - s.lastPos);
                transform.position -= Vector3.ProjectOnPlane(d, transform.up) * dragGain;
                s.lastPos = p;
            }
        }

        void TwoHandTurn()
        {
            Vector3 a = hands[0].input.PinchPosition, b = hands[1].input.PinchPosition;
            Vector3 mid = (a + b) / 2, span = b - a;
            if (twoHanded)
            {
                var space = HandInput.TrackingSpace(origin);
                Vector3 d = space.TransformVector(mid - lastMid);
                transform.position -= Vector3.ProjectOnPlane(d, transform.up) * dragGain;
                float yaw = Vector3.SignedAngle(Vector3.ProjectOnPlane(span, Vector3.up),
                                                Vector3.ProjectOnPlane(lastSpan, Vector3.up), Vector3.up);
                origin.RotateAroundCameraUsingOriginUp(yaw); // hands turn clockwise -> world turns with them
            }
            foreach (var h in hands) h.mode = Mode.Drag; // releasing one hand continues as a drag
            lastMid = mid; lastSpan = span; twoHanded = true;
            foreach (var h in hands) h.lastPos = h.input.PinchPosition;
        }

        void Controllers()
        {
            var head = origin.Camera != null ? origin.Camera.transform : transform;
            Vector3 forward = Vector3.ProjectOnPlane(head.forward, transform.up).normalized;
            Vector3 right = Vector3.Cross(transform.up, forward);
            Vector2 stick = move.ReadValue<Vector2>();
            transform.position += (forward * stick.y + right * stick.x) * (stickSpeed * Time.deltaTime);

            float x = turn.ReadValue<Vector2>().x;
            if (turnReady && Mathf.Abs(x) > 0.7f)
            {
                origin.RotateAroundCameraUsingOriginUp(Mathf.Sign(x) * snapTurnDegrees);
                turnReady = false;
            }
            else if (Mathf.Abs(x) < 0.3f) turnReady = true;

            if (reset.WasPressedThisFrame()) ResetToSpawn();
        }
    }
}
