"use client";

import {
  formatCountryCardNote,
  formatCountryName,
  type CanaryResponse,
} from "@/lib/canary-format";

/**
 * The card we show when we know the country but NOT the city.
 *
 * Deliberately has no Leaflet import and no tile dependency: a country is not a
 * point, and drawing a pin at a country centroid is the exact fabrication this
 * whole display policy exists to prevent. The server has already omitted the
 * coordinates, so there is nothing here that could be plotted even by mistake.
 */
export function CanaryCountryCard({ response }: { response: CanaryResponse }) {
  const country = formatCountryName(response.geo?.country_code);
  const note = formatCountryCardNote(response);

  return (
    <div className="ob-country-card" data-testid="canary-country-card">
      {country && (
        <div className="ob-country-name" data-testid="canary-country-name">
          {country}
        </div>
      )}
      <p className="ob-map-note" data-testid="canary-country-note">
        {note}
      </p>
    </div>
  );
}

export default CanaryCountryCard;
