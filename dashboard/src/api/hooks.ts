import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";

const STALE = 30_000; // 30s
const SIGNAL_STALE = 60_000; // 60s for cross-source signals
const SYSTEM_STALE = 30_000; // 30s for agent monitoring

export function useOverview() {
  return useQuery({ queryKey: ["overview"], queryFn: api.overview, staleTime: STALE });
}

export function usePulse(params?: Record<string, string>) {
  return useQuery({ queryKey: ["pulse", params], queryFn: () => api.pulse(params), staleTime: STALE });
}

export function useDebates() {
  return useQuery({ queryKey: ["debates"], queryFn: api.debates, staleTime: STALE });
}

export function useLeaders(params?: Record<string, string>) {
  return useQuery({ queryKey: ["leaders", params], queryFn: () => api.leaders(params), staleTime: STALE });
}

export function useResearch() {
  return useQuery({ queryKey: ["research"], queryFn: api.research, staleTime: STALE });
}

export function useFunding() {
  return useQuery({ queryKey: ["funding"], queryFn: api.funding, staleTime: STALE });
}

export function useJobs() {
  return useQuery({ queryKey: ["jobs"], queryFn: api.jobs, staleTime: STALE });
}

export function useNewsImpact() {
  return useQuery({ queryKey: ["newsImpact"], queryFn: api.newsImpact, staleTime: STALE });
}

export function useGeo() {
  return useQuery({ queryKey: ["geo"], queryFn: api.geo, staleTime: STALE });
}

export function useTopics(params?: Record<string, string>) {
  return useQuery({ queryKey: ["topics", params], queryFn: () => api.topics(params), staleTime: STALE });
}

export function useTopic(id: number) {
  return useQuery({ queryKey: ["topic", id], queryFn: () => api.topic(id), staleTime: STALE, enabled: !!id });
}

export function useTopicTimeline(id: number) {
  return useQuery({ queryKey: ["topicTimeline", id], queryFn: () => api.topicTimeline(id), staleTime: STALE, enabled: !!id });
}

export function useTopicPosts(id: number, params?: Record<string, string>) {
  return useQuery({ queryKey: ["topicPosts", id, params], queryFn: () => api.topicPosts(id, params), staleTime: STALE, enabled: !!id });
}

export function usePersonas(params?: Record<string, string>) {
  return useQuery({ queryKey: ["personas", params], queryFn: () => api.personas(params), staleTime: STALE });
}

export function usePersona(id: number) {
  return useQuery({ queryKey: ["persona", id], queryFn: () => api.persona(id), staleTime: STALE, enabled: !!id });
}

export function usePersonaPosts(id: number, params?: Record<string, string>) {
  return useQuery({ queryKey: ["personaPosts", id, params], queryFn: () => api.personaPosts(id, params), staleTime: STALE, enabled: !!id });
}

export function usePersonaGraph(id: number) {
  return useQuery({ queryKey: ["personaGraph", id], queryFn: () => api.personaGraph(id), staleTime: STALE, enabled: !!id });
}

export function useNews(params?: Record<string, string>) {
  return useQuery({ queryKey: ["news", params], queryFn: () => api.news(params), staleTime: STALE });
}

export function useSearch(q: string) {
  return useQuery({ queryKey: ["search", q], queryFn: () => api.search(q), staleTime: STALE, enabled: q.length >= 2 });
}

export function useHealth() {
  return useQuery({ queryKey: ["health"], queryFn: api.health, staleTime: 10_000, refetchInterval: 30_000 });
}

export function useSpendingStatus() {
  return useQuery({
    queryKey: ["spendingStatus"],
    queryFn: api.spending,
    staleTime: 10_000,
    refetchInterval: 15_000,
  });
}

export function useSignalForgeDaily() {
  return useQuery({
    queryKey: ["signalforgeDaily"],
    queryFn: api.signalforgeDaily,
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
}

export function useSignalForgeStatus() {
  return useQuery({
    queryKey: ["signalforgeStatus"],
    queryFn: api.signalforgeStatus,
    staleTime: 2_000,
    refetchInterval: 5_000,
  });
}

export function useSignalForgeStrategicPortfolio() {
  return useQuery({
    queryKey: ["signalforgeStrategicPortfolio"],
    queryFn: api.signalforgeBrainStrategicPortfolio,
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
}

export function useSignalForgeBrainThesis(id: string) {
  return useQuery({
    queryKey: ["signalforgeBrainThesis", id],
    queryFn: () => api.signalforgeBrainThesis(id),
    staleTime: 30_000,
    enabled: !!id,
  });
}

export function useSignalForgeResearchWorkspace() {
  return useQuery({
    queryKey: ["signalforgeResearchWorkspace"],
    queryFn: api.signalforgeBrainResearchWorkspace,
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
}

export function useSignalForgeBrainSearch(q: string) {
  return useQuery({
    queryKey: ["signalforgeBrainSearch", q],
    queryFn: () => api.signalforgeBrainSearch(q),
    staleTime: STALE,
    enabled: q.trim().length >= 2,
  });
}

export function useSignalForgeBrainStatus() {
  return useQuery({
    queryKey: ["signalforgeBrainStatus"],
    queryFn: api.signalforgeBrainStatus,
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
}

export function useSignalForgeFounderProfile() {
  return useQuery({
    queryKey: ["signalforgeFounderProfile"],
    queryFn: api.signalforgeFounderProfile,
    staleTime: 5 * 60_000,
  });
}

export function useSignalForgeOperatingQueue() {
  return useQuery({
    queryKey: ["signalforgeOperatingQueue"],
    queryFn: api.signalforgeOperatingQueue,
    staleTime: 10_000,
    refetchInterval: 30_000,
  });
}

export function useSignalForgeMoneyTrails() {
  return useQuery({
    queryKey: ["signalforgeMoneyTrails"],
    queryFn: api.signalforgeMoneyTrails,
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
}

export function useSignalForgeMoneyTrail(id: string) {
  return useQuery({
    queryKey: ["signalforgeMoneyTrail", id],
    queryFn: () => api.signalforgeMoneyTrail(id),
    staleTime: 30_000,
    enabled: !!id,
  });
}

export function useProbeSignalForgeMoneyTrail() {
  return useMutation({ mutationFn: api.probeSignalForgeMoneyTrail });
}

export function useProbeSignalForgeFounderIdea() {
  return useMutation({ mutationFn: api.probeSignalForgeFounderIdea });
}

export function useFalsifySignalForge() {
  return useMutation({ mutationFn: api.falsifySignalForge });
}

export function useSignalForgeEvidenceReplay(thesisId: string, enabled = true) {
  return useQuery({
    queryKey: ["signalforgeEvidenceReplay", thesisId],
    queryFn: () => api.signalforgeEvidenceReplay(thesisId),
    enabled: enabled && !!thesisId && !thesisId.startsWith("probe:"),
    staleTime: 30_000,
  });
}

export function useSignalForgeDecisionPortfolio(params?:{limit?:number;weekly_hours?:number;cash_need?:string;long_term?:string}) {
  return useQuery({ queryKey:["signalforgeDecisionPortfolio",params], queryFn:()=>api.signalforgeDecisionPortfolio(params), staleTime:30_000, refetchInterval:60_000 });
}

export function useCompareSignalForgeDecisions() {
  return useMutation({ mutationFn: api.compareSignalForgeDecisions });
}

export function useAskSignalForgeDecision() {
  return useMutation({ mutationFn: api.askSignalForgeDecision });
}

export function useSignalForgeBenchmarkBatch() {
  return useMutation({ mutationFn: api.signalforgeBenchmarkBatch });
}

export function useSignalForgeDecisionWatch() {
  return useQuery({ queryKey:["signalforgeDecisionWatch"], queryFn:api.signalforgeDecisionWatch, staleTime:30_000, refetchInterval:60_000 });
}


export function useSignalForgeChatGPTStatus() {
  return useQuery({ queryKey:["signalforgeChatGPTStatus"], queryFn:api.signalforgeChatGPTStatus, staleTime:15_000 });
}

export function useSignalForgeDiscussionPacket(thesisId:string) {
  return useQuery({ queryKey:["signalforgeDiscussionPacket",thesisId], queryFn:()=>api.signalforgeDiscussionPacket(thesisId), enabled:!!thesisId, staleTime:15_000 });
}

export function useSignalForgeDecisionArtifacts(status?:string) {
  return useQuery({ queryKey:["signalforgeDecisionArtifacts",status], queryFn:()=>api.signalforgeDecisionArtifacts(status), staleTime:2_000, refetchInterval:5_000 });
}

export function usePrepareSignalForgeDecisionArtifact() {
  const qc=useQueryClient();
  return useMutation({ mutationFn:api.prepareSignalForgeDecisionArtifact, onSuccess:()=>qc.invalidateQueries({queryKey:["signalforgeDecisionArtifacts"]}) });
}

export function useConfirmSignalForgeDecisionArtifact() {
  const qc=useQueryClient();
  return useMutation({ mutationFn:(artifactId:string)=>api.confirmSignalForgeDecisionArtifact(artifactId), onSuccess:()=>{ qc.invalidateQueries({queryKey:["signalforgeDecisionArtifacts"]}); qc.invalidateQueries({queryKey:["signalforgeFounderMemory"]}); qc.invalidateQueries({queryKey:["signalforgeFounderMemorySubjects"]}); } });
}

export function useRejectSignalForgeDecisionArtifact() {
  const qc=useQueryClient();
  return useMutation({ mutationFn:({artifactId,reason}:{artifactId:string;reason?:string})=>api.rejectSignalForgeDecisionArtifact(artifactId,reason), onSuccess:()=>qc.invalidateQueries({queryKey:["signalforgeDecisionArtifacts"]}) });
}

export function useSignalForgeFounderMemorySubjects() {
  return useQuery({ queryKey: ["signalforgeFounderMemorySubjects"], queryFn: api.signalforgeFounderMemorySubjects, staleTime: 5_000 });
}

export function useSignalForgeFounderMemory(subjectKey: string, thesisId?: string) {
  return useQuery({ queryKey: ["signalforgeFounderMemory", subjectKey, thesisId], queryFn: () => api.signalforgeFounderMemory(subjectKey, thesisId), enabled: subjectKey.trim().length >= 2, staleTime: 2_000 });
}

export function useSignalForgeFounderMemoryBrief(subjectKey: string, thesisId?: string) {
  return useQuery({ queryKey: ["signalforgeFounderMemoryBrief", subjectKey, thesisId], queryFn: () => api.signalforgeFounderMemoryBrief(subjectKey, thesisId), enabled: subjectKey.trim().length >= 2, staleTime: 2_000 });
}

export function useSignalForgeFounderMemoryDelta(subjectKey: string, thesisId?: string) {
  return useQuery({ queryKey: ["signalforgeFounderMemoryDelta", subjectKey, thesisId], queryFn: () => api.signalforgeFounderMemoryDelta(subjectKey, thesisId), enabled: subjectKey.trim().length >= 2, staleTime: 2_000 });
}

export function useRecordSignalForgeFounderMemory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.recordSignalForgeFounderMemory,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["signalforgeFounderMemory"] });
      qc.invalidateQueries({ queryKey: ["signalforgeFounderMemorySubjects"] });
      qc.invalidateQueries({ queryKey: ["signalforgeFounderMemoryBrief"] });
      qc.invalidateQueries({ queryKey: ["signalforgeFounderMemoryDelta"] });
    },
  });
}

export function useCheckpointSignalForgeFounderMemory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.checkpointSignalForgeFounderMemory,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["signalforgeFounderMemoryDelta"] });
      qc.invalidateQueries({ queryKey: ["signalforgeFounderMemorySubjects"] });
    },
  });
}

export function useSignalForgeMarketActions() {
  return useQuery({
    queryKey: ["signalforgeMarketActions"],
    queryFn: api.signalforgeMarketActions,
    staleTime: 10_000,
    refetchInterval: 30_000,
  });
}

export function useRegisterSignalForgeMarketAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.registerSignalForgeMarketAction,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["signalforgeMarketActions"] });
      qc.invalidateQueries({ queryKey: ["signalforgeOperatingQueue"] });
      qc.invalidateQueries({ queryKey: ["signalforgeDaily"] });
      qc.invalidateQueries({ queryKey: ["signalforgeStrategicPortfolio"] });
    },
  });
}

export function useCompleteSignalForgeMarketAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({actionId,payload}:{actionId:string;payload:{result:string;observations?:Record<string,unknown>;note?:string}}) => api.completeSignalForgeMarketAction(actionId,payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["signalforgeMarketActions"] });
      qc.invalidateQueries({ queryKey: ["signalforgeOperatingQueue"] });
      qc.invalidateQueries({ queryKey: ["signalforgeDaily"] });
      qc.invalidateQueries({ queryKey: ["signalforgeBrainStatus"] });
    },
  });
}

export function useSignalForgeMarketExecution() {
  return useQuery({ queryKey:["signalforgeMarketExecution"], queryFn:()=>api.signalforgeMarketExecution(50), staleTime:10_000, refetchInterval:30_000 });
}

export function useDesignSignalForgeMarketTest() {
  return useMutation({ mutationFn: api.designSignalForgeMarketTest });
}

export function usePreregisterSignalForgeMarketTest() {
  const qc=useQueryClient();
  return useMutation({ mutationFn: api.preregisterSignalForgeMarketTest, onSuccess:()=>{ qc.invalidateQueries({queryKey:["signalforgeMarketExecution"]}); qc.invalidateQueries({queryKey:["signalforgeMarketActions"]}); } });
}

export function useSignalForgeClaimPreregistrationOptions(actionId:string|undefined) {
  return useQuery({ queryKey:["signalforgeClaimPreregistrationOptions",actionId], queryFn:()=>api.signalforgeClaimPreregistrationOptions(actionId || ""), enabled:!!actionId, staleTime:5_000 });
}

export function usePreregisterSignalForgeClaimForAction() {
  const qc=useQueryClient();
  return useMutation({ mutationFn:({actionId,payload}:{actionId:string;payload:{case_id:number;claim_code:string;note?:string}})=>api.preregisterSignalForgeClaimForAction(actionId,payload), onSuccess:()=>{ qc.invalidateQueries({queryKey:["signalforgeMarketExecution"]}); qc.invalidateQueries({queryKey:["signalforgeValidationExperiments"]}); qc.invalidateQueries({queryKey:["signalforgeClaimPreregistrationOptions"]}); } });
}

export function useCaptureSignalForgeMarketOutcome() {
  const qc=useQueryClient();
  return useMutation({ mutationFn:({actionId,payload}:{actionId:string;payload:{outcome_counts:Record<string,number>;actor_labels:string[];evidence_refs:string[];observation_records?:Array<{observation_id?:string;actor_label:string;evidence_ref:string;observed_behavior?:string;decision_relevant_finding?:string;signals?:Record<string,unknown>}>;observed_behavior?:string;decision_relevant_findings?:string;reason_counts?:Record<string,number>;amount?:number;currency?:string;actual_cost?:number;actual_cost_currency?:string;note?:string}})=>api.captureSignalForgeMarketOutcome(actionId,payload), onSuccess:()=>{ qc.invalidateQueries({queryKey:["signalforgeMarketExecution"]}); qc.invalidateQueries({queryKey:["signalforgeMarketActions"]}); qc.invalidateQueries({queryKey:["signalforgeMarketLearningCalibration"]}); } });
}

export function useSignalForgePromotionOptions(actionId:string|undefined) {
  return useQuery({ queryKey:["signalforgePromotionOptions",actionId], queryFn:()=>api.signalforgePromotionOptions(actionId || ""), enabled:!!actionId, staleTime:5_000 });
}

export function usePromoteSignalForgeMarketOutcome() {
  const qc=useQueryClient();
  return useMutation({ mutationFn:({actionId,payload}:{actionId:string;payload:{experiment_id:string;note?:string}})=>api.promoteSignalForgeMarketOutcome(actionId,payload), onSuccess:()=>{ qc.invalidateQueries({queryKey:["signalforgePromotionOptions"]}); qc.invalidateQueries({queryKey:["signalforgeMarketExecution"]}); qc.invalidateQueries({queryKey:["signalforgeValidationExperiments"]}); qc.invalidateQueries({queryKey:["signalforgeStrategicPortfolio"]}); qc.invalidateQueries({queryKey:["signalforgeMarketLearningCalibration"]}); } });
}

export function useSignalForgeMarketLearningCalibration() {
  return useQuery({ queryKey:["signalforgeMarketLearningCalibration"], queryFn:api.signalforgeMarketLearningCalibration, staleTime:15_000, refetchInterval:60_000 });
}

export function useSignalForgeValidationExperiments() {
  return useQuery({
    queryKey: ["signalforgeValidationExperiments"],
    queryFn: api.signalforgeValidationExperiments,
    staleTime: 10_000,
    refetchInterval: 30_000,
  });
}

export function useRegisterSignalForgeValidationExperiment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.registerSignalForgeValidationExperiment,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["signalforgeValidationExperiments"] });
      qc.invalidateQueries({ queryKey: ["signalforgeDaily"] });
    },
  });
}

export function useRecordSignalForgeValidationResult() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({experimentId,payload}:{experimentId:string;payload:{result:string;note:string;event?:string;actor_label?:string;amount?:number;currency?:string}}) => api.recordSignalForgeValidationResult(experimentId,payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["signalforgeValidationExperiments"] });
      qc.invalidateQueries({ queryKey: ["signalforgeDaily"] });
      qc.invalidateQueries({ queryKey: ["signalforgeOperatingQueue"] });
      qc.invalidateQueries({ queryKey: ["signalforgeBrainStatus"] });
      qc.invalidateQueries({ queryKey: ["signalforgeStrategicPortfolio"] });
    },
  });
}

export function useSignalForgeOpportunityDetail(id: number) {
  return useQuery({
    queryKey: ["signalforgeOpportunityDetail", id],
    queryFn: () => api.signalforgeOpportunity(id),
    staleTime: SIGNAL_STALE,
    enabled: !!id,
  });
}

export function useSignalForgeResearchState(id: number) {
  return useQuery({
    queryKey: ["signalforgeResearchState", id],
    queryFn: () => api.signalforgeResearchState(id),
    staleTime: 15_000,
    enabled: !!id,
  });
}

export function useSignalForgeResearchMore(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.signalforgeResearchMore(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["signalforgeResearchState", id] });
    },
  });
}

export function useTriggerSignalForge() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.triggerSignalForge,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["signalforgeDaily"] });
      qc.invalidateQueries({ queryKey: ["signalforgeStatus"] });
      qc.invalidateQueries({ queryKey: ["signalforgeOperatingQueue"] });
    },
  });
}

// Intelligence hooks
export function useProducts(params?: Record<string, string>) {
  return useQuery({ queryKey: ["products", params], queryFn: () => api.products(params), staleTime: STALE });
}

export function useMigrations() {
  return useQuery({ queryKey: ["migrations"], queryFn: api.migrations, staleTime: STALE });
}

export function useUnmetNeeds() {
  return useQuery({ queryKey: ["unmetNeeds"], queryFn: api.unmetNeeds, staleTime: STALE });
}

export function useJobAnalysis() {
  return useQuery({ queryKey: ["jobAnalysis"], queryFn: api.jobAnalysis, staleTime: STALE });
}

// Job Intelligence hooks (LLM-extracted)
export function useJobIntelSummary() {
  return useQuery({ queryKey: ["jobIntelSummary"], queryFn: api.jobIntelSummary, staleTime: STALE });
}

export function useJobIntelTechStack(params?: Record<string, string>) {
  return useQuery({ queryKey: ["jobIntelTechStack", params], queryFn: () => api.jobIntelTechStack(params), staleTime: STALE });
}

export function useJobIntelSalary(params?: Record<string, string>) {
  return useQuery({ queryKey: ["jobIntelSalary", params], queryFn: () => api.jobIntelSalary(params), staleTime: STALE });
}

export function useJobIntelHiring(params?: Record<string, string>) {
  return useQuery({ queryKey: ["jobIntelHiring", params], queryFn: () => api.jobIntelHiring(params), staleTime: STALE });
}

export function useJobIntelGeo() {
  return useQuery({ queryKey: ["jobIntelGeo"], queryFn: api.jobIntelGeo, staleTime: STALE });
}

export function useJobIntelAI() {
  return useQuery({ queryKey: ["jobIntelAI"], queryFn: api.jobIntelAI, staleTime: STALE });
}

export function useJobIntelStages() {
  return useQuery({ queryKey: ["jobIntelStages"], queryFn: api.jobIntelStages, staleTime: STALE });
}

export function useJobIntelBenefits() {
  return useQuery({ queryKey: ["jobIntelBenefits"], queryFn: api.jobIntelBenefits, staleTime: STALE });
}

export function useJobIntelSkills(params?: Record<string, string>) {
  return useQuery({ queryKey: ["jobIntelSkills", params], queryFn: () => api.jobIntelSkills(params), staleTime: STALE });
}

export function useHypeIndex(params?: Record<string, string>) {
  return useQuery({ queryKey: ["hypeIndex", params], queryFn: () => api.hypeIndex(params), staleTime: STALE });
}

export function usePainPoints(params?: Record<string, string>) {
  return useQuery({ queryKey: ["painPoints", params], queryFn: () => api.painPoints(params), staleTime: STALE });
}

export function useLeaderShifts() {
  return useQuery({ queryKey: ["leaderShifts"], queryFn: api.leaderShifts, staleTime: STALE });
}

export function useFundingRounds(params?: Record<string, string>) {
  return useQuery({ queryKey: ["fundingRounds", params], queryFn: () => api.fundingRounds(params), staleTime: STALE });
}

export function useTopicPlatformTones(id: number) {
  return useQuery({ queryKey: ["topicPlatformTones", id], queryFn: () => api.topicPlatformTones(id), staleTime: STALE, enabled: !!id });
}

// Founder Opportunity Radar
export function useOpportunitySummary(){return useQuery({queryKey:["opportunitySummary"],queryFn:api.opportunitySummary,staleTime:SIGNAL_STALE,refetchInterval:SIGNAL_STALE});}
export function useOpportunities(params?:Record<string,string>){return useQuery({queryKey:["opportunities",params],queryFn:()=>api.opportunities(params),staleTime:SIGNAL_STALE,refetchInterval:SIGNAL_STALE});}
export function useOpportunity(id:number){return useQuery({queryKey:["opportunity",id],queryFn:()=>api.opportunity(id),staleTime:SIGNAL_STALE,enabled:!!id});}
export function useUpdateOpportunityStatus(){const qc=useQueryClient();return useMutation({mutationFn:({id,status}:{id:number;status:string})=>api.updateOpportunityStatus(id,status),onSuccess:(_d,v)=>{qc.invalidateQueries({queryKey:["opportunities"]});qc.invalidateQueries({queryKey:["opportunitySummary"]});qc.invalidateQueries({queryKey:["opportunity",v.id]});}});}

export function useProblemCandidateSummary(){return useQuery({queryKey:["problemCandidateSummary"],queryFn:api.problemCandidateSummary,staleTime:SIGNAL_STALE,refetchInterval:SIGNAL_STALE});}
export function useProblemCandidates(params?:Record<string,string>){return useQuery({queryKey:["problemCandidates",params],queryFn:()=>api.problemCandidates(params),staleTime:SIGNAL_STALE,refetchInterval:SIGNAL_STALE});}
export function useProblemCandidate(id:number){return useQuery({queryKey:["problemCandidate",id],queryFn:()=>api.problemCandidate(id),staleTime:SIGNAL_STALE,enabled:!!id});}
export function useUpdateProblemCandidateStatus(){const qc=useQueryClient();return useMutation({mutationFn:({id,status}:{id:number;status:string})=>api.updateProblemCandidateStatus(id,status),onSuccess:(_d,v)=>{qc.invalidateQueries({queryKey:["problemCandidates"]});qc.invalidateQueries({queryKey:["problemCandidateSummary"]});qc.invalidateQueries({queryKey:["problemCandidate",v.id]});qc.invalidateQueries({queryKey:["signalforgeDaily"]});}});}
// ── Cross-Source Signal Hooks ─────────────────────────────────

export function useResearchPipeline(params?: Record<string, string>) {
  return useQuery({ queryKey: ["researchPipeline", params], queryFn: () => api.researchPipeline(params), staleTime: SIGNAL_STALE, refetchInterval: SIGNAL_STALE });
}

export function useTractionScores(params?: Record<string, string>) {
  return useQuery({ queryKey: ["tractionScores", params], queryFn: () => api.tractionScores(params), staleTime: SIGNAL_STALE, refetchInterval: SIGNAL_STALE });
}

export function useTechnologyLifecycle(params?: Record<string, string>) {
  return useQuery({ queryKey: ["technologyLifecycle", params], queryFn: () => api.technologyLifecycle(params), staleTime: SIGNAL_STALE, refetchInterval: SIGNAL_STALE });
}

export function useMarketGaps(params?: Record<string, string>) {
  return useQuery({ queryKey: ["marketGaps", params], queryFn: () => api.marketGaps(params), staleTime: SIGNAL_STALE, refetchInterval: SIGNAL_STALE });
}

export function useCompetitiveThreats(params?: Record<string, string>) {
  return useQuery({ queryKey: ["competitiveThreats", params], queryFn: () => api.competitiveThreats(params), staleTime: SIGNAL_STALE, refetchInterval: SIGNAL_STALE });
}

export function usePlatformDivergence(params?: Record<string, string>) {
  return useQuery({ queryKey: ["platformDivergence", params], queryFn: () => api.platformDivergence(params), staleTime: SIGNAL_STALE, refetchInterval: SIGNAL_STALE });
}

export function useSmartMoney(params?: Record<string, string>) {
  return useQuery({ queryKey: ["smartMoney", params], queryFn: () => api.smartMoney(params), staleTime: SIGNAL_STALE, refetchInterval: SIGNAL_STALE });
}

export function useTalentFlow(params?: Record<string, string>) {
  return useQuery({ queryKey: ["talentFlow", params], queryFn: () => api.talentFlow(params), staleTime: SIGNAL_STALE, refetchInterval: SIGNAL_STALE });
}

export function useNarrativeShifts(params?: Record<string, string>) {
  return useQuery({ queryKey: ["narrativeShifts", params], queryFn: () => api.narrativeShifts(params), staleTime: SIGNAL_STALE, refetchInterval: SIGNAL_STALE });
}

export function useSignalSummary() {
  return useQuery({ queryKey: ["signalSummary"], queryFn: api.signalSummary, staleTime: SIGNAL_STALE, refetchInterval: SIGNAL_STALE });
}

export function useInsights(params?: Record<string, string>) {
  return useQuery({ queryKey: ["insights", params], queryFn: () => api.insights(params), staleTime: SIGNAL_STALE, refetchInterval: SIGNAL_STALE });
}

export function useCrossSourceHighlights() {
  return useQuery({ queryKey: ["crossSourceHighlights"], queryFn: api.crossSourceHighlights, staleTime: SIGNAL_STALE, refetchInterval: SIGNAL_STALE });
}

// ── Agent Management Hooks ────────────────────────────────────

export function useAgentStatus() {
  return useQuery({ queryKey: ["agentStatus"], queryFn: api.agentStatus, staleTime: SYSTEM_STALE, refetchInterval: SYSTEM_STALE });
}

export function useAgentRuns(params?: Record<string, string>) {
  return useQuery({ queryKey: ["agentRuns", params], queryFn: () => api.agentRuns(params), staleTime: SYSTEM_STALE, refetchInterval: SYSTEM_STALE });
}

export function useAgentRunDetail(id: number) {
  return useQuery({ queryKey: ["agentRunDetail", id], queryFn: () => api.agentRunDetail(id), staleTime: SYSTEM_STALE, enabled: !!id });
}

export function useAgentCosts(params?: Record<string, string>) {
  return useQuery({ queryKey: ["agentCosts", params], queryFn: () => api.agentCosts(params), staleTime: SYSTEM_STALE });
}

export function useTriggerAgent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.triggerAgent(name),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["agentStatus"] }); qc.invalidateQueries({ queryKey: ["agentRuns"] }); },
  });
}

export function useTriggerAllAgents() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.triggerAllAgents(),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["agentStatus"] }); qc.invalidateQueries({ queryKey: ["agentRuns"] }); },
  });
}

export function useAgentOutput(name: string) {
  return useQuery({ queryKey: ["agentOutput", name], queryFn: () => api.agentOutput(name), staleTime: SIGNAL_STALE, enabled: !!name });
}

// ── Source Data Hooks ─────────────────────────────────────────

export function useGithubTrending(params?: Record<string, string>) {
  return useQuery({ queryKey: ["githubTrending", params], queryFn: () => api.githubTrending(params), staleTime: SIGNAL_STALE });
}

export function useHfTrending(params?: Record<string, string>) {
  return useQuery({ queryKey: ["hfTrending", params], queryFn: () => api.hfTrending(params), staleTime: SIGNAL_STALE });
}

export function usePackageTrends(params?: Record<string, string>) {
  return useQuery({ queryKey: ["packageTrends", params], queryFn: () => api.packageTrends(params), staleTime: SIGNAL_STALE });
}

export function useYcBatches(params?: Record<string, string>) {
  return useQuery({ queryKey: ["ycBatches", params], queryFn: () => api.ycBatches(params), staleTime: SIGNAL_STALE });
}

export function useSoTrends(params?: Record<string, string>) {
  return useQuery({ queryKey: ["soTrends", params], queryFn: () => api.soTrends(params), staleTime: SIGNAL_STALE });
}

export function usePhRecent(params?: Record<string, string>) {
  return useQuery({ queryKey: ["phRecent", params], queryFn: () => api.phRecent(params), staleTime: SIGNAL_STALE });
}

// ── Product Reviews Hooks ────────────────────────────────────

export function useProductReviews(params?: Record<string, string>) {
  return useQuery({ queryKey: ["productReviews", params], queryFn: () => api.productReviews(params), staleTime: STALE });
}

export function useProductReviewSummary() {
  return useQuery({ queryKey: ["productReviewSummary"], queryFn: api.productReviewSummary, staleTime: STALE });
}

// ── Gig Board Hooks ──────────────────────────────────────────

export function useGigBoard(params?: Record<string, string>) {
  return useQuery({ queryKey: ["gigBoard", params], queryFn: () => api.gigBoard(params), staleTime: STALE });
}

export function useGigSummary() {
  return useQuery({ queryKey: ["gigSummary"], queryFn: api.gigSummary, staleTime: STALE });
}

export function useGigTrends() {
  return useQuery({ queryKey: ["gigTrends"], queryFn: api.gigTrends, staleTime: STALE });
}

// ── Custom Market Research Hooks ────────────────────────────

export function useResearchProjects(params?: Record<string, string>) {
  return useQuery({ queryKey: ["researchProjects", params], queryFn: () => api.researchProjects(params), staleTime: STALE });
}

export function useResearchProject(id: number) {
  return useQuery({ queryKey: ["researchProject", id], queryFn: () => api.researchProject(id), staleTime: 5_000, enabled: !!id, refetchInterval: 5_000 });
}

export function useResearchInsights(id: number) {
  return useQuery({ queryKey: ["researchInsights", id], queryFn: () => api.researchInsights(id), staleTime: STALE, enabled: !!id });
}

export function useResearchContacts(id: number, params?: Record<string, string>) {
  return useQuery({ queryKey: ["researchContacts", id, params], queryFn: () => api.researchContacts(id, params), staleTime: STALE, enabled: !!id });
}

export function useResearchPosts(id: number, params?: Record<string, string>) {
  return useQuery({ queryKey: ["researchPosts", id, params], queryFn: () => api.researchPosts(id, params), staleTime: STALE, enabled: !!id });
}

export function useCreateResearch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { name: string; description?: string; initial_terms: string[] }) => api.createResearchProject(data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["researchProjects"] }); },
  });
}

export function useRunResearch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.runResearch(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["researchProjects"] }); },
  });
}

export function useDeleteResearch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.deleteResearch(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["researchProjects"] }); },
  });
}
