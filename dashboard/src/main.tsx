import "./signalforgeResearchPersistenceV253";
// FounderDecisionQueueV3 retired from canonical homepage: Candidate backlog is evidence drill-down only.
import "./signalforgeFounderRuntimeClosure"; // SIGNALFORGE_FOUNDER_USABILITY_EVIDENCE_PRECISION_CLOSURE_V1
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
