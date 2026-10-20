using UnityEngine;

namespace VRDirector
{
    /// <summary>
    /// Layers that keep the shot clean: the room (splat / point cloud) is on "Scene",
    /// and the shot and preview cameras render only that layer, so hands, menus,
    /// camera models and the path never appear in a video. The progress screen is on
    /// "UI", which is all the headset shows while a shot renders.
    /// </summary>
    public static class SceneLayers
    {
        public const string SceneName = "Scene";

        public static int Scene => LayerMask.NameToLayer(SceneName);
        public static int Overlay => LayerMask.NameToLayer("UI");

        /// <summary>Only the room; everything if the "Scene" layer is missing.</summary>
        public static int SceneMask => Scene >= 0 ? 1 << Scene : ~0;

        public static void SetLayerRecursively(GameObject go, int layer)
        {
            foreach (var t in go.GetComponentsInChildren<Transform>(true)) t.gameObject.layer = layer;
        }
    }
}
