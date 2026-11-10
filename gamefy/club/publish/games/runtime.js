export function isClubNavigation(search = globalThis.location?.search || '', embedded = globalThis.MoyuClubRuntime?.embedded === true) {
  return embedded || new URLSearchParams(search).get('club') === '1';
}

export function platformLoading(sdk, search = globalThis.location?.search || '', embedded = globalThis.MoyuClubRuntime?.embedded === true) {
  return isClubNavigation(search, embedded) ? null : sdk?.loading ?? null;
}
