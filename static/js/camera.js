// Small webcam helper shared by the sign-up and punch-in pages.
const Camera = {
  async start(video, overlay) {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      overlay.textContent = "Camera not available. Open this page on http://localhost or over HTTPS.";
      return false;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 960 }, facingMode: "user" },
        audio: false,
      });
      video.srcObject = stream;
      await video.play();
      overlay.hidden = true;
      return true;
    } catch (err) {
      overlay.textContent = "Camera blocked: " + err.message + ". Allow camera access and reload.";
      return false;
    }
  },

  // JPEG data URL of the current frame (not mirrored, so it matches the real face).
  snapshot(video, maxWidth = 960) {
    const scale = Math.min(1, maxWidth / video.videoWidth);
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/jpeg", 0.9);
  },
};

function getCookie(name) {
  const m = document.cookie.match("(^|;)\\s*" + name + "=([^;]*)");
  return m ? decodeURIComponent(m[2]) : "";
}
