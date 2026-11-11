/** Opens Google Maps with directions to the customer's door. No starting point is given, so Google Maps starts from the
 *  rider's current location. The "api=1" is only the version of Google's link format; it needs no key and costs nothing. */
export function directionsUrl(lat: number, lng: number) {
  return `https://www.google.com/maps/dir/?api=1&destination=${lat},${lng}&travelmode=two-wheeler&dir_action=navigate`;
}

/** For an address with no saved position yet: opens Google Maps searching for the address text. */
export function searchUrl(text: string) {
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(text)}`;
}