import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import Quickshell.Services.Pipewire
import qs.Ui
import qs.Commons
import "Model.js" as Model

Panel {
  id: root
  moduleName: "reedme.blackshark"
  ipcTarget: "reedme.blackshark"

  readonly property var nodes: Pipewire.nodes ? Pipewire.nodes.values : []
  readonly property color foreground: (bar && bar.foreground) ? bar.foreground : "#cacccc"
  readonly property color accent: (bar && bar.urgent) ? bar.urgent : "#a55555"
  readonly property color dim: Qt.darker(foreground, 1.5)
  readonly property color background: (bar && bar.background) ? bar.background : "#101315"
  readonly property string fontFamily: (bar && bar.fontFamily) ? bar.fontFamily : "sans-serif"
  readonly property int barSize: bar ? bar.barSize : Style.bar.sizeHorizontal
  readonly property string helperPath: String(Qt.resolvedUrl("ctl.py")).replace(/^file:\/\//, "")
  readonly property string udevPath: String(Qt.resolvedUrl("install-udev.sh")).replace(/^file:\/\//, "")
  readonly property string rulePath: String(Qt.resolvedUrl("99-razer-blackshark-v3.rules")).replace(/^file:\/\//, "")

  readonly property var gameSink: {
    for (var i = 0; i < nodes.length; i++)
      if (Model.isGameSink(nodes[i])) return nodes[i]
    return null
  }
  readonly property var chatSink: {
    for (var i = 0; i < nodes.length; i++)
      if (Model.isChatSink(nodes[i])) return nodes[i]
    return null
  }
  readonly property var chatSource: {
    for (var i = 0; i < nodes.length; i++)
      if (Model.isChatSource(nodes[i])) return nodes[i]
    return null
  }

  readonly property bool connected: !!(gameSink || chatSink || hid.connected)
  readonly property real gameVol: Model.volumeOf(gameSink)
  readonly property real chatVol: Model.volumeOf(chatSink)
  readonly property bool gameMuted: gameSink && gameSink.audio ? gameSink.audio.muted : false
  readonly property bool chatMuted: chatSink && chatSink.audio ? chatSink.audio.muted : false

  readonly property var gameApps: {
    var list = []
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i]
      if (!Model.isPlaybackStream(n) || !n.audio || n.audio.muted) continue
      if (!Model.streamIsChatApp(n)) list.push(Model.streamLabel(n))
    }
    return list
  }
  readonly property var chatApps: {
    var list = []
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i]
      if (!Model.isPlaybackStream(n) || !n.audio || n.audio.muted) continue
      if (Model.streamIsChatApp(n)) list.push(Model.streamLabel(n))
    }
    return list
  }

  QtObject {
    id: hid
    property bool connected: false
    property bool permission: false
    property bool needsUdev: false
    property bool live: false
    property string hidraw: ""
    property string error: ""
    property int eqPreset: 1
    property string eqPresetName: "Game"
    property var eqBands: [2, 2, 5, 5, 1, -1, 2, 3, 3, 3]
    property var eqFreqs: ["31", "63", "125", "250", "500", "1k", "2k", "4k", "8k", "16k"]
    property int sidetone: 0
    property bool thx: false
    property bool ull: false
    property int mix: 10
    property int micEq: 0
    property string micEqName: "Default"
    property bool prompts: true
    property int fn: 0
    property string fnName: "Game/Chat"
    property int powerSave: 15
    property int led: 0
    property string ledName: "Connection"
    property var battery: null
    property var charging: null
    property var micMuted: null
    property bool debug: false
    property bool debugAllowed: false
    property var debugLines: []
  }

  property var pendingSet: null
  property bool wantBattery: false
  property real lastBatteryPoll: 0
  property bool monitorWanted: true

  readonly property bool batteryLow: hid.battery !== null && hid.battery !== undefined && hid.battery >= 0 && hid.battery < 10

  readonly property string batteryText: {
    if (hid.battery === null || hid.battery === undefined || hid.battery < 0)
      return "--%"
    return (hid.charging === true ? "󰂄 " : "") + hid.battery + "%"
  }

  readonly property string barLabel: {
    var icon = root.connected ? "󰋋 " : "󰟎 "
    return icon + root.batteryText
  }

  readonly property string tooltip: {
    if (!root.connected) return "BlackShark V3 disconnected"
    var lines = ["BlackShark V3  ·  " + hid.eqPresetName + "  ·  " + root.batteryText]
    if (hid.battery === null || hid.battery === undefined)
      lines.push("Battery GET is still 0xFF (dongle not-ready). Audio works; live % needs a Windows-sized USB config read.")
    lines.push("EQ " + hid.eqBands.map(function(v) { return Model.dbLabel(v) }).join(" "))
    lines.push("Sidetone " + hid.sidetone + "/15  ·  Mix " + Model.mixLabel(hid.mix))
    var flags = []
    if (hid.thx) flags.push("THX")
    if (hid.ull) flags.push("ULL")
    if (hid.micMuted === true) flags.push("Mic mute")
    if (flags.length) lines.push(flags.join("  ·  "))
    lines.push("Game send " + Math.round(root.gameVol * 100) + "%  ·  Chat send " + Math.round(root.chatVol * 100) + "%")
    if (hid.needsUdev) lines.push("HID access needed for live EQ / sidetone.")
    return lines.join("\n")
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  PwObjectTracker {
    objects: {
      var list = []
      if (root.gameSink) list.push(root.gameSink)
      if (root.chatSink) list.push(root.chatSink)
      if (root.chatSource) list.push(root.chatSource)
      return list
    }
  }

  function setSinkVolume(node, value) {
    if (!node || !node.audio) return
    node.audio.volume = Math.max(0, Math.min(1, value))
    if (value > 0) node.audio.muted = false
  }

  function appendDebug(ev) {
    if (!ev || !hid.debugAllowed || !hid.debug) return
    var dir = ev.dir === "out" ? "→" : "←"
    var name = ev.name || "?"
    var args = (ev.args && ev.args.length) ? " [" + ev.args.join(" ") + "]" : ""
    var extra = ""
    if (ev.kind) extra += " " + ev.kind
    if (ev.via) extra += " " + ev.via
    var line = dir + " " + name + args + extra
    if (ev.hex) line += "  " + ev.hex
    var lines = hid.debugLines.slice()
    lines.push(line)
    if (lines.length > 8) lines = lines.slice(lines.length - 8)
    hid.debugLines = lines
  }

  function applyHid(raw) {
    var parsed = Model.parseHid(raw)
    if (parsed.type === "hid") {
      root.appendDebug(parsed)
      var cls = Number(parsed.cls)
      var v = (parsed.args && parsed.args.length) ? Number(parsed.args[0]) : NaN
      if ((cls === 0x5c || cls === 0x65) && v >= 0 && v <= 20) hid.mix = v
      if (cls === 0x19 && v >= 0 && v <= 15) hid.sidetone = v
      return
    }
    if (parsed.debug && parsed.debug.length) {
      for (var i = 0; i < parsed.debug.length; i++) root.appendDebug(parsed.debug[i])
    }
    if (!parsed.ok && parsed.error) {
      hid.error = parsed.error
      return
    }
    hid.connected = parsed.connected === true
    hid.permission = parsed.permission === true
    hid.needsUdev = parsed.needsUdev === true
    hid.live = parsed.live === true
    hid.hidraw = String(parsed.hidraw || "")
    hid.error = String(parsed.error || "")
    if (parsed.eqPreset !== undefined) hid.eqPreset = Number(parsed.eqPreset)
    if (parsed.eqPresetName) hid.eqPresetName = String(parsed.eqPresetName)
    if (parsed.eqBands && parsed.eqBands.length === 10) hid.eqBands = parsed.eqBands.slice()
    if (parsed.eqFreqs && parsed.eqFreqs.length === 10) hid.eqFreqs = parsed.eqFreqs.slice()
    if (parsed.sidetone !== undefined) hid.sidetone = Number(parsed.sidetone)
    if (parsed.thx !== undefined) hid.thx = parsed.thx === true
    if (parsed.ull !== undefined) hid.ull = parsed.ull === true
    if (parsed.mix !== undefined) hid.mix = Number(parsed.mix)
    if (parsed.micEq !== undefined) hid.micEq = Number(parsed.micEq)
    if (parsed.micEqName) hid.micEqName = String(parsed.micEqName)
    if (parsed.prompts !== undefined) hid.prompts = parsed.prompts === true
    if (parsed.fn !== undefined) hid.fn = Number(parsed.fn)
    if (parsed.fnName) hid.fnName = String(parsed.fnName)
    if (parsed.powerSave !== undefined) hid.powerSave = Number(parsed.powerSave)
    if (parsed.led !== undefined) hid.led = Number(parsed.led)
    if (parsed.ledName) hid.ledName = String(parsed.ledName)
    if (parsed.battery !== undefined) hid.battery = parsed.battery
    if (parsed.charging !== undefined) hid.charging = parsed.charging
    if (parsed.micMuted !== undefined) hid.micMuted = parsed.micMuted
    if (parsed.debugAllowed !== undefined) {
      hid.debugAllowed = parsed.debugAllowed === true
      if (!hid.debugAllowed && hid.debug) {
        hid.debug = false
        hid.debugLines = []
      }
    }
  }

  function refreshHid() {
    if (statusProc.running || setProc.running) return
    var now = Date.now() / 1000
    var cmd = ["python3", "-B", root.helperPath, "status"]
    if (now - root.lastBatteryPoll >= 300) {
      cmd.push("--battery")
      root.lastBatteryPoll = now
    }
    statusProc.command = cmd
    statusProc.running = true
  }

  function runSet(kind, values) {
    if (setProc.running) {
      root.pendingSet = { kind: kind, values: values }
      return
    }
    var cmd = ["python3", "-B", root.helperPath, "set", kind]
    for (var i = 0; i < values.length; i++) cmd.push(String(values[i]))
    setProc.command = cmd
    setProc.running = true
  }

  function grantHid() {
    if (udevProc.running) return
    udevProc.command = ["pkexec", root.udevPath, root.rulePath]
    udevProc.running = true
  }

  function toggleDebug() {
    if (!hid.debugAllowed) return
    hid.debug = !hid.debug
    hid.debugLines = hid.debug
      ? ["HID debug on — click Sidetone or use headset buttons"]
      : []
    root.monitorWanted = false
    Qt.callLater(function() { root.monitorWanted = true })
  }

  onOpenedChanged: {
    if (opened) refreshHid()
  }

  Timer {
    interval: 300000
    repeat: true
    running: true
    triggeredOnStart: true
    onTriggered: root.refreshHid()
  }

  Timer {
    id: eqDebounce
    interval: 280
    repeat: false
    onTriggered: root.runSet("eq-bands", hid.eqBands)
  }

  Process {
    id: statusProc
    running: false
    command: []
    stdout: StdioCollector { id: statusOut; waitForEnd: true }
    stderr: StdioCollector { id: statusErr; waitForEnd: true }
    onExited: function(code) {
      var text = String(statusOut.text || "")
      if (code === 0 && text) root.applyHid(text)
      else if (String(statusErr.text || "")) hid.error = String(statusErr.text)
    }
  }

  Process {
    id: setProc
    running: false
    command: []
    stdout: StdioCollector { id: setOut; waitForEnd: true }
    stderr: StdioCollector { id: setErr; waitForEnd: true }
    onExited: function(code) {
      var text = String(setOut.text || "")
      if (text) root.applyHid(text)
      else if (code !== 0) hid.error = String(setErr.text || "HID set failed")
      if (root.pendingSet) {
        var next = root.pendingSet
        root.pendingSet = null
        root.runSet(next.kind, next.values)
      }
    }
  }

  Process {
    id: udevProc
    running: false
    command: []
    stdout: StdioCollector { waitForEnd: true }
    stderr: StdioCollector { id: udevErr; waitForEnd: true }
    onExited: function(code) {
      if (code !== 0) hid.error = String(udevErr.text || "Could not grant HID access")
      else hid.error = ""
      root.refreshHid()
    }
  }

  Process {
    id: monitorProc
    running: hid.permission && root.monitorWanted
    command: (hid.debugAllowed && hid.debug)
      ? ["python3", "-u", "-B", root.helperPath, "monitor", "--poll-mix", "--debug"]
      : ["python3", "-u", "-B", root.helperPath, "monitor", "--poll-mix"]
    stdout: SplitParser {
      onRead: function(line) { root.applyHid(line) }
    }
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.barLabel
    fontSize: Style.bar.iconFont
    tooltipText: root.tooltip
    active: root.batteryLow
    onPressed: function(b) { root.toggle() }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened

    readonly property bool useWide: availableCardWidth >= Style.space(720)
    readonly property int splitGap: Style.space(16)

    contentWidth: panel.fittedContentWidth(useWide ? Style.space(860) : Style.space(460))
    contentHeight: panel.fittedContentHeight(column.implicitHeight)

    Column {
      id: column
      width: parent.width
      spacing: Style.space(8)

      Item {
        width: parent.width
        implicitHeight: Math.max(title.implicitHeight, meta.implicitHeight)
        Text {
          id: title
          text: "BlackShark V3"
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.title
          font.bold: true
          anchors.left: parent.left
          anchors.verticalCenter: parent.verticalCenter
        }
        Text {
          id: meta
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          color: hid.debug ? root.accent : root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
          text: root.batteryText + (hid.debugAllowed ? (hid.debug ? "  HID" : "  debug") : "")
          MouseArea {
            anchors.fill: parent
            enabled: hid.debugAllowed
            cursorShape: hid.debugAllowed ? Qt.PointingHandCursor : Qt.ArrowCursor
            onClicked: root.toggleDebug()
          }
        }
      }

      Button {
        visible: hid.debugAllowed
        width: parent.width
        text: hid.debug ? "HID debug on" : "Show HID debug"
        selected: hid.debug
        foreground: root.foreground
        accent: root.accent
        onClicked: root.toggleDebug()
      }

      Text {
        width: parent.width
        wrapMode: Text.WordWrap
        visible: hid.error !== ""
        text: hid.error
        color: root.accent
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }

      Button {
        visible: hid.needsUdev
        width: parent.width
        text: "Grant HID access"
        foreground: root.foreground
        accent: root.accent
        onClicked: root.grantHid()
      }

      Text {
        width: parent.width
        visible: hid.debugAllowed && hid.debug
        wrapMode: Text.WrapAnywhere
        text: hid.debugLines.length ? hid.debugLines.join("\n") : "waiting for HID…"
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        maximumLineCount: 8
      }

      Item {
        width: parent.width
        implicitHeight: panel.useWide
          ? Math.max(eqCol.implicitHeight, ctrlCol.implicitHeight)
          : eqCol.implicitHeight + ctrlCol.implicitHeight + panel.splitGap

        Column {
          id: eqCol
          width: panel.useWide ? (parent.width - panel.splitGap) * 0.52 : parent.width
          spacing: Style.space(8)
          x: 0
          y: 0

          Flow {
            width: parent.width
            spacing: Style.space(4)
            Repeater {
              model: ["Default", "Game", "Movie", "Music", "Esports"]
              Chip {
                required property int index
                required property string modelData
                text: modelData
                selected: hid.eqPreset === index
                onClicked: {
                  hid.eqPreset = index
                  hid.eqPresetName = modelData
                  hid.eqBands = [2, 2, 5, 5, 1, -1, 2, 3, 3, 3]
                  if (index === 0) hid.eqBands = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
                  if (index === 2) hid.eqBands = [3, 3, 3, -1, -4, -4, 2, 3, 3, 3]
                  if (index === 3) hid.eqBands = [2, 2, 0, 0, 1, -1, -1, 3, 3, 3]
                  if (index === 4) hid.eqBands = [1, 1, -1, 0, 2, 0, 4, 4, 4, -3]
                  root.runSet("eq", [index])
                }
              }
            }
          }

          Row {
            id: eqRow
            width: parent.width
            spacing: Style.space(4)
            Repeater {
              model: 10
              EqColumn {
                required property int index
                width: (eqRow.width - eqRow.spacing * 9) / 10
                label: hid.eqFreqs[index] || ""
                value: Number(hid.eqBands[index] || 0)
                onMoved: function(v) {
                  var next = hid.eqBands.slice()
                  next[index] = v
                  hid.eqBands = next
                  eqDebounce.restart()
                }
              }
            }
          }
        }

        Column {
          id: ctrlCol
          width: panel.useWide ? (parent.width - panel.splitGap) * 0.48 : parent.width
          spacing: Style.space(8)
          x: panel.useWide ? parent.width - width : 0
          y: panel.useWide ? 0 : eqCol.implicitHeight + panel.splitGap

          SliderRow {
            width: parent.width
            label: "SIDETONE"
            readout: hid.sidetone + "/15"
            minimum: 0
            maximum: 15
            value: hid.sidetone
            onReleased: function(v) {
              hid.sidetone = Math.round(v)
              root.runSet("sidetone", [hid.sidetone])
            }
          }
          Text {
            width: parent.width
            wrapMode: Text.WordWrap
            text: "Mic monitoring in the cups — unmute the boom mic and speak. This is not Game/Chat mix."
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }

          SliderRow {
            width: parent.width
            label: "MIX"
            readout: Model.mixLabel(hid.mix)
            minimum: 0
            maximum: 20
            tickCount: 5
            value: hid.mix
            onReleased: function(v) {
              hid.mix = Math.round(v)
              root.runSet("mix", [hid.mix])
            }
          }

          Flow {
            width: parent.width
            spacing: Style.space(4)
            Chip { text: "THX"; selected: hid.thx; onClicked: { hid.thx = !hid.thx; root.runSet("thx", [hid.thx ? "on" : "off"]) } }
            Chip { text: "ULL"; selected: hid.ull; onClicked: { hid.ull = !hid.ull; root.runSet("ull", [hid.ull ? "on" : "off"]) } }
            Chip { text: "Prompts"; selected: hid.prompts; onClicked: { hid.prompts = !hid.prompts; root.runSet("prompts", [hid.prompts ? "on" : "off"]) } }
          }

          PanelSectionHeader { text: "MIC EQ"; foreground: root.foreground; fontFamily: root.fontFamily }
          Flow {
            width: parent.width
            spacing: Style.space(4)
            Repeater {
              model: ["Default", "Esports", "Broadcast", "Mic Boost"]
              Chip {
                required property int index
                required property string modelData
                text: modelData
                selected: hid.micEq === index
                onClicked: { hid.micEq = index; hid.micEqName = modelData; root.runSet("mic-eq", [index]) }
              }
            }
          }

          PanelSectionHeader { text: "FN"; foreground: root.foreground; fontFamily: root.fontFamily }
          Flow {
            width: parent.width
            spacing: Style.space(4)
            Repeater {
              model: ["Game/Chat", "Sidetone", "Footsteps", "BT vol"]
              Chip {
                required property int index
                required property string modelData
                text: modelData
                selected: hid.fn === index
                onClicked: { hid.fn = index; hid.fnName = modelData; root.runSet("fn", [index]) }
              }
            }
          }

          PanelSectionHeader { text: "LED"; foreground: root.foreground; fontFamily: root.fontFamily }
          Flow {
            width: parent.width
            spacing: Style.space(4)
            Repeater {
              model: ["Link", "Batt", "Warn"]
              Chip {
                required property int index
                required property string modelData
                text: modelData
                selected: hid.led === index
                onClicked: { hid.led = index; hid.ledName = modelData; root.runSet("led", [index]) }
              }
            }
          }

          PanelSectionHeader { text: "AUTO OFF"; foreground: root.foreground; fontFamily: root.fontFamily }
          Flow {
            width: parent.width
            spacing: Style.space(4)
            Repeater {
              model: [
                { value: 0, label: "Off" },
                { value: 15, label: "15m" },
                { value: 30, label: "30m" },
                { value: 45, label: "45m" },
                { value: 60, label: "60m" }
              ]
              Chip {
                required property var modelData
                text: modelData.label
                selected: hid.powerSave === modelData.value
                onClicked: { hid.powerSave = modelData.value; root.runSet("power-save", [modelData.value]) }
              }
            }
          }

          PanelSeparator { foreground: root.foreground }

          SliderRow {
            width: parent.width
            label: "GAME"
            readout: Math.round(root.gameVol * 100) + "%"
            extra: root.gameApps.length ? "LIVE" : (root.gameMuted ? "MUTED" : "")
            minimum: 0
            maximum: 1
            integer: false
            value: root.gameVol
            onReleased: function(v) { root.setSinkVolume(root.gameSink, v) }
          }
          SliderRow {
            width: parent.width
            label: "CHAT"
            readout: Math.round(root.chatVol * 100) + "%"
            extra: root.chatApps.length ? "LIVE" : (root.chatMuted ? "MUTED" : "")
            minimum: 0
            maximum: 1
            integer: false
            value: root.chatVol
            onReleased: function(v) { root.setSinkVolume(root.chatSink, v) }
          }
        }
      }
    }
  }

  component Chip: Button {
    foreground: root.foreground
    accent: root.accent
    fontFamily: root.fontFamily
    fontSize: Style.font.caption
  }

  component SliderRow: Column {
    id: srow
    property string label: ""
    property string readout: ""
    property string extra: ""
    property real minimum: 0
    property real maximum: 1
    property real value: 0
    property bool integer: true
    property int tickCount: 0
    signal released(real value)
    spacing: Style.space(2)

    Item {
      width: parent.width
      implicitHeight: Math.max(sLabel.implicitHeight, sRead.implicitHeight)
      Text {
        id: sLabel
        text: srow.label + (srow.extra !== "" ? "  " + srow.extra : "")
        color: srow.extra === "LIVE" ? root.accent : root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
      }
      Text {
        id: sRead
        text: srow.readout
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
      }
    }
    PanelSlider {
      width: parent.width
      bar: root.bar
      minimum: srow.minimum
      maximum: srow.maximum
      step: srow.integer ? 1 : 0.05
      integer: srow.integer
      tickCount: srow.tickCount
      value: srow.value
      fillColor: root.accent
      knobColor: root.foreground
      tickColor: root.background
      onReleased: function(v) { srow.released(v) }
    }
  }

  component EqColumn: Column {
    id: eqc
    property string label: ""
    property int value: 0
    signal moved(int value)
    spacing: Style.space(2)

    Text {
      width: parent.width
      horizontalAlignment: Text.AlignHCenter
      text: eqc.label
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      font.bold: true
    }

    Item {
      id: eqTrack
      width: parent.width
      height: Style.space(72)

      readonly property real t: (eqc.value + 6) / 12

      Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        width: Math.max(Style.space(6), parent.width * 0.45)
        height: parent.height
        radius: width / 2
        color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.14)
      }
      Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        width: Math.max(Style.space(6), parent.width * 0.45)
        height: Math.max(width, parent.height * eqTrack.t)
        radius: width / 2
        color: root.accent
      }

      MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        function fromY(y) {
          var n = 6 - Math.round((y / Math.max(1, height)) * 12)
          return Math.max(-6, Math.min(6, n))
        }
        onPressed: function(m) { eqc.moved(fromY(m.y)) }
        onPositionChanged: function(m) { if (pressed) eqc.moved(fromY(m.y)) }
      }
    }

    Text {
      width: parent.width
      horizontalAlignment: Text.AlignHCenter
      text: Model.dbLabel(eqc.value)
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      font.bold: true
    }
  }
}
