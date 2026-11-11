import { useEffect, useRef } from "react";
import { StyleProp, View, ViewStyle } from "react-native";
import { WebView, WebViewMessageEvent } from "react-native-webview";

// The map pictures come from OpenStreetMap volunteers. Their own tile server is meant for light use, and the credit line is
// required. If many people use your app, put the address of a tile service you are allowed to use here (it is one line).
const TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";

export type MapMarker = { id: string; lat: number; lng: number; emoji: string; label?: string; smooth?: boolean };
export type MapState = {
  markers?: MapMarker[];
  line?: { from: [number, number]; to: [number, number] } | null;
  pin?: { lat: number; lng: number } | null;   // a draggable pin (for choosing a place)
  pinMode?: boolean;                            // tapping the map moves the pin
  recenterKey?: string;                         // change it to move the view to the pin
  fitKey?: string;                              // change it to zoom so every marker is visible
  padBottom?: number;                           // space covered by a panel at the bottom
};

const html = `<!doctype html><html><head>
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<style>
html,body,#map{height:100%;margin:0;padding:0;background:#e5e7eb}
.emoji{background:none;border:none}
.emoji div{font-size:30px;line-height:34px;text-align:center}
.leaflet-control-attribution{font-size:9px}
</style></head><body><div id="map"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<script>
var map = L.map("map").setView([26.7855, 79.0215], 14);
L.tileLayer("${TILE_URL}", { maxZoom: 19, attribution: "&copy; OpenStreetMap contributors" }).addTo(map);
var markers = {}, line = null, pinMarker = null, pinMode = false, lastFit = null, lastRecenter = null;

function send(o) { window.ReactNativeWebView.postMessage(JSON.stringify(o)); }
function icon(e, low) { return L.divIcon({ className: "emoji", html: "<div>" + e + "</div>", iconSize: [34, 34], iconAnchor: [17, low ? 32 : 17] }); }

function glide(m, to) {
  var from = m.getLatLng(), t0 = Date.now(), ms = 1500;
  if (m._raf) cancelAnimationFrame(m._raf);
  (function step() {
    var k = Math.min(1, (Date.now() - t0) / ms);
    m.setLatLng([from.lat + (to[0] - from.lat) * k, from.lng + (to[1] - from.lng) * k]);
    if (k < 1) m._raf = requestAnimationFrame(step);
  })();
}

function setPin(latlng, fromUser) {
  if (!pinMarker) {
    pinMarker = L.marker(latlng, { draggable: true, icon: icon("📍", true) }).addTo(map);
    pinMarker.on("dragend", function () { var p = pinMarker.getLatLng(); send({ type: "pin", lat: p.lat, lng: p.lng }); });
  } else pinMarker.setLatLng(latlng);
  if (fromUser) { var q = pinMarker.getLatLng(); send({ type: "pin", lat: q.lat, lng: q.lng }); }
}
map.on("click", function (e) { if (pinMode) setPin(e.latlng, true); });

window.update = function (s) {
  pinMode = !!s.pinMode;
  var list = s.markers || [], seen = {};
  list.forEach(function (d) {
    seen[d.id] = true;
    var m = markers[d.id];
    if (!m) {
      m = L.marker([d.lat, d.lng], { icon: icon(d.emoji, false) }).addTo(map);
      if (d.label) m.bindTooltip(d.label);
      markers[d.id] = m;
    } else if (d.smooth) glide(m, [d.lat, d.lng]);
    else m.setLatLng([d.lat, d.lng]);
  });
  Object.keys(markers).forEach(function (id) { if (!seen[id]) { map.removeLayer(markers[id]); delete markers[id]; } });

  if (line) { map.removeLayer(line); line = null; }
  if (s.line) line = L.polyline([s.line.from, s.line.to], { color: "#0f766e", weight: 4, dashArray: "8 8" }).addTo(map);

  if (s.pin) {
    var had = !!pinMarker;
    setPin([s.pin.lat, s.pin.lng], false);
    if (!had) map.setView([s.pin.lat, s.pin.lng], 16);
  }
  if (s.recenterKey && s.recenterKey !== lastRecenter && s.pin) {
    lastRecenter = s.recenterKey;
    map.setView([s.pin.lat, s.pin.lng], 17);
  }
  if (s.fitKey && s.fitKey !== lastFit) {
    lastFit = s.fitKey;
    var pts = list.map(function (d) { return [d.lat, d.lng]; });
    if (pts.length > 1) map.fitBounds(pts, { paddingTopLeft: [50, 50], paddingBottomRight: [50, 50 + (s.padBottom || 0)] });
    else if (pts.length === 1) map.setView(pts[0], 16);
  }
};
send({ type: "ready" });
</script></body></html>`;

export default function OsmMap({ state, onPin, style }: {
  state: MapState;
  onPin?: (p: { lat: number; lng: number }) => void;
  style?: StyleProp<ViewStyle>;
}) {
  const web = useRef<WebView>(null);
  const ready = useRef(false);
  const latest = useRef(state);
  latest.current = state;

  const push = () => {
    if (ready.current) web.current?.injectJavaScript(`window.update(${JSON.stringify(latest.current)}); true;`);
  };
  const key = JSON.stringify(state);
  useEffect(() => { push(); }, [key]);

  const onMessage = (e: WebViewMessageEvent) => {
    try {
      const m = JSON.parse(e.nativeEvent.data);
      if (m.type === "ready") { ready.current = true; push(); }
      else if (m.type === "pin") onPin?.({ lat: m.lat, lng: m.lng });
    } catch { /* ignore */ }
  };

  return (
    <View style={[{ flex: 1, overflow: "hidden", backgroundColor: "#e5e7eb" }, style]}>
      <WebView
        ref={web}
        originWhitelist={["*"]}
        source={{ html }}
        javaScriptEnabled
        domStorageEnabled
        scrollEnabled={false}
        overScrollMode="never"
        setSupportMultipleWindows={false}
        onMessage={onMessage}
        style={{ flex: 1, backgroundColor: "#e5e7eb" }}
      />
    </View>
  );
}