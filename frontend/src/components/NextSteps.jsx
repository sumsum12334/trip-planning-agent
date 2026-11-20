export function NextSteps({ suggestions, onSelect, disabled }) {
  if (!suggestions.length) return null;
  return <div className="next-steps">
    <span className="next-steps-label">Next steps</span>
    <div className="next-step-chips">
      {suggestions.map((suggestion) => (
        <button key={suggestion} type="button" className="next-step-chip" disabled={disabled} onClick={() => onSelect(suggestion)}>{suggestion}</button>
      ))}
    </div>
  </div>;
}
