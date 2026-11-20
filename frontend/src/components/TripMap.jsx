import { useEffect, useMemo, useRef } from "react";
import L from "leaflet";
import { escapeHtml, routePoints } from "../lib/planUtils.js";

export function numberedIcon(number, kind) {
  return L.divIcon({
    className: kind === "airport" ? "trip-map-marker airport" : "trip-map-marker",
    html: `<span>${kind === "airport" ? "✈" : number}</span>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
    popupAnchor: [0, -14],
  });
}

export function TripMap({ plan }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const points = useMemo(() => routePoints(plan), [plan]);

  useEffect(() => {
    const container = containerRef.current;
    if (mapRef.current) {
      mapRef.current.remove();
      mapRef.current = null;
    }
    if (!container || !points.length) return undefined;
    const map = L.map(container, { scrollWheelZoom: false });
    mapRef.current = map;
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);
    const latlngs = points.map((point) => [point.lat, point.lng]);
    points.forEach((point, index) => {
      L.marker([point.lat, point.lng], { icon: numberedIcon(index + 1, point.kind) })
        .addTo(map)
        .bindPopup(`<strong>${escapeHtml(point.label)}</strong>${point.sub ? `<br/>${escapeHtml(point.sub)}` : ""}`);
    });
    if (latlngs.length > 1) {
      L.polyline(latlngs, { color: "#6c63ff", weight: 3, opacity: 0.75, dashArray: "6 8" }).addTo(map);
    }
    map.fitBounds(L.latLngBounds(latlngs), { padding: [28, 28], maxZoom: 12 });
    const resizeTimer = window.setTimeout(() => map.invalidateSize(), 120);
    return () => {
      window.clearTimeout(resizeTimer);
      map.remove();
      mapRef.current = null;
    };
  }, [points]);

  if (!points.length) {
    return <div className="trip-map-fallback">
      <p>No coordinates were provided for this plan, so the route cannot be drawn on the map.</p>
      <div className="trip-map-links">
        <a href={`https://www.openstreetmap.org/search?query=${encodeURIComponent(plan.destination)}`} target="_blank" rel="noopener noreferrer">Open {plan.destination} on OpenStreetMap</a>
        <a href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(plan.destination)}`} target="_blank" rel="noopener noreferrer">Search on Google Maps</a>
      </div>
    </div>;
  }

  return <div className="trip-map-wrap">
    <div className="trip-map" ref={containerRef} />
    <small className="trip-map-note">Route points are approximate and may not reflect exact addresses.</small>
  </div>;
}
