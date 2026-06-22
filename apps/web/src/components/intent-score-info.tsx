// Plain-language explanation of the intent score, shown inside the InfoTooltip
// on the visitors list. Kept faithful to the backend formula in
// apps/api/services/visitor_aggregator.py::calculate_intent_score() — if the
// weights change there, update this copy too.

export function IntentScoreInfo() {
  return (
    <div className="space-y-2">
      <p className="font-medium text-foreground">How intent is scored (0–100)</p>
      <p className="text-muted-foreground">
        We add points for signals that suggest buying interest, then weight by how
        recently they visited.
      </p>
      <ul className="space-y-1 text-muted-foreground">
        <li>
          <span className="font-medium text-foreground">Visits:</span> 3+ → +25, 2 → +15
        </li>
        <li>
          <span className="font-medium text-foreground">Engagement:</span> scrolled 75%+ → +15;
          avg 60s+ per page → +10
        </li>
        <li>
          <span className="font-medium text-foreground">Return cadence:</span> back within 2 days
          → +15 (within 5 days → +8)
        </li>
        <li>
          <span className="font-medium text-foreground">Funnel depth:</span> reached 2 / 3 / 4+
          page types → +5 / +10 / +15
        </li>
        <li>
          <span className="font-medium text-foreground">Source:</span> direct or search → +10,
          email → +8, referral → +5, social or paid → +3
        </li>
        <li>
          <span className="font-medium text-foreground">Recency:</span> ×1.0 today · ×0.9 this week
          · ×0.7 this month · ×0.4 within 90 days · ×0.2 older
        </li>
      </ul>
      <p className="text-muted-foreground">
        <span className="font-medium text-foreground">40+</span> unlocks identity resolution ·{" "}
        <span className="font-medium text-foreground">60+</span> triggers social intelligence.
      </p>
    </div>
  );
}
