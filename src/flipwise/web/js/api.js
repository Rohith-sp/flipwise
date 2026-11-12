// Thin fetch wrappers. Errors carry the API's message so the UI can show it.
export class ApiError extends Error {}
async function req(path, opts) {
  let r;
  try { r = await fetch(path, opts); } catch (e) { throw new ApiError("Cannot reach the live server"); }
  let body = null;
  try { body = await r.json(); } catch (e) { /* non-JSON body */ }
  if (!r.ok) throw new ApiError((body && body.message) || `HTTP ${r.status}`);
  return body;
}
const post = (path, body) => req(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
export const getStatus = () => req("/status");
export const getClock = () => req("/clock");
export const getHealth = () => req("/health");
export const getHistory = (since) => req(since == null ? "/history" : `/history?since=${since}`);
export const getDc = (id, policy) => req(`/dc/${id}${policy ? `?policy=${encodeURIComponent(policy)}` : ""}`);
export const getJobs = () => req("/jobs");
export const getJob = (id) => req(`/jobs/${encodeURIComponent(id)}`);
export const getResults = () => req("/results");
export const postJob = (body) => post("/jobs", body);
export const postControl = (body) => post("/control", body);
export const getActivity = (policy, since) => req(`/activity?policy=${encodeURIComponent(policy)}${since == null ? "" : `&since=${since}`}`);
export const getLanes = (policy) => req(`/lanes?policy=${encodeURIComponent(policy)}`);
