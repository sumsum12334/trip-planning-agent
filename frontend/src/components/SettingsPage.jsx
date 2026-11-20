import { ModelSettings } from "./ModelSettings.jsx";
import { TripAssistanceSettings } from "./TripAssistanceSettings.jsx";

export function SettingsPage() {
  return <section className="page">
    <div className="page-title"><div><p className="eyebrow">CONFIGURATION</p><h1>Settings</h1><p className="muted">Model endpoint, runtime options, and trip assistance for the running backend.</p></div><span className="hero-icon">⚙</span></div>
    <ModelSettings />
    <TripAssistanceSettings />
  </section>;
}
