function nodeProps(node) {
  return node && node.ready && node.properties ? node.properties : {}
}

function blob(node) {
  if (!node) return ""
  var p = nodeProps(node)
  return String([
    node.name || "",
    node.description || "",
    node.nickname || "",
    p["node.description"] || "",
    p["device.profile.name"] || "",
    p["device.profile.description"] || ""
  ].join(" ")).toLowerCase()
}

function isBlackShark(node) {
  return blob(node).indexOf("blackshark") !== -1 || blob(node).indexOf("blackshark_v3") !== -1
}

function isGameSink(node) {
  if (!node || !node.isSink || node.isStream) return false
  var b = blob(node)
  return (b.indexOf("stereo-game") !== -1 || /\bgame\b/.test(b)) && isBlackShark(node)
}

function isChatSink(node) {
  if (!node || !node.isSink || node.isStream) return false
  var b = blob(node)
  return (b.indexOf("stereo-chat") !== -1 || /\bchat\b/.test(b)) && isBlackShark(node)
}

function isChatSource(node) {
  if (!node || node.isSink || node.isStream) return false
  var b = blob(node)
  return isBlackShark(node) && (b.indexOf("chat") !== -1 || b.indexOf("mono-chat") !== -1)
}

function isPlaybackStream(node) {
  if (!node || !node.isStream) return false
  if (node.isSink === true) return true
  var mediaClass = String(node.type || "")
  return mediaClass.indexOf("Stream/Output/Audio") !== -1
    || mediaClass.indexOf("AudioOutStream") !== -1
}

function streamLabel(node) {
  if (!node) return "App"
  var p = nodeProps(node)
  return p["application.name"] || node.description || p["media.name"] || node.name || "App"
}

function streamIsChatApp(node) {
  var label = streamLabel(node).toLowerCase()
  var p = nodeProps(node)
  var role = String(p["media.role"] || "").toLowerCase()
  var target = String(p["target.object"] || p["node.target"] || "").toLowerCase()
  if (target.indexOf("stereo-chat") !== -1) return true
  if (target.indexOf("stereo-game") !== -1) return false
  if (role === "communication" || role === "phone") return true
  if (label.indexOf("webrtc") !== -1) return true
  if (label === "zoom" || label === "slack" || label.indexOf("teams") !== -1) return true
  if (label.indexOf("skype") !== -1 || label.indexOf("mumble") !== -1) return true
  if (label.indexOf("teamspeak") !== -1 || label.indexOf("steam voice") !== -1) return true
  return false
}

function volumeOf(node) {
  if (!node || !node.audio) return 0
  if (node.audio.muted) return 0
  return Number(node.audio.volume) || 0
}

function mixPosition(gameVol, chatVol) {
  var g = Math.max(0, gameVol)
  var c = Math.max(0, chatVol)
  var sum = g + c
  if (sum <= 0.001) return 0.5
  return c / sum
}

function parseHid(raw) {
  try {
    var o = JSON.parse(String(raw || ""))
    if (!o || typeof o !== "object") return { ok: false, error: "bad json" }
    return o
  } catch (e) {
    return { ok: false, error: String(e) }
  }
}

function mixLabel(value) {
  var n = Number(value)
  if (!isFinite(n)) return "Center"
  if (n <= 0) return "Game"
  if (n >= 20) return "Chat"
  if (n === 10) return "Center"
  return n < 10 ? "Game +" + (10 - n) : "Chat +" + (n - 10)
}

function dbLabel(value) {
  var n = Number(value)
  if (!isFinite(n) || n === 0) return "0"
  return (n > 0 ? "+" : "") + n
}

if (typeof module !== "undefined") {
  module.exports = {
    nodeProps: nodeProps,
    isGameSink: isGameSink,
    isChatSink: isChatSink,
    isChatSource: isChatSource,
    isPlaybackStream: isPlaybackStream,
    streamLabel: streamLabel,
    streamIsChatApp: streamIsChatApp,
    volumeOf: volumeOf,
    mixPosition: mixPosition,
    parseHid: parseHid,
    mixLabel: mixLabel,
    dbLabel: dbLabel
  }
}
