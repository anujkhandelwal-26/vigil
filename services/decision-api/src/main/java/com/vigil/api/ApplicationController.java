package com.vigil.api;

import com.vigil.api.dto.ApplicationSubmitRequest;
import com.vigil.api.dto.ApplicationSummary;
import com.vigil.api.dto.DecisionResponse;
import com.vigil.api.dto.FeedbackRequest;
import com.vigil.domain.AnalystFeedback;
import com.vigil.domain.Application;
import com.vigil.domain.AppUser;
import com.vigil.repo.AnalystFeedbackRepository;
import com.vigil.repo.AppUserRepository;
import com.vigil.repo.ApplicationRepository;
import com.vigil.repo.DecisionRepository;
import com.vigil.service.AuditService;
import com.vigil.service.DecisionService;
import com.vigil.service.MlClient;
import com.vigil.service.QueryService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.Pattern;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;
import java.util.NoSuchElementException;
import java.util.UUID;

@RestController
@RequestMapping("/api/v1/applications")
public class ApplicationController {

    private final DecisionService decisionService;
    private final QueryService queryService;
    private final ApplicationRepository applicationRepository;
    private final DecisionRepository decisionRepository;
    private final AnalystFeedbackRepository feedbackRepository;
    private final MlClient mlClient;
    private final AuditService auditService;
    private final AppUserRepository appUserRepository;

    public ApplicationController(DecisionService decisionService, QueryService queryService,
                                  ApplicationRepository applicationRepository, DecisionRepository decisionRepository,
                                  AnalystFeedbackRepository feedbackRepository, MlClient mlClient,
                                  AuditService auditService, AppUserRepository appUserRepository) {
        this.decisionService = decisionService;
        this.queryService = queryService;
        this.applicationRepository = applicationRepository;
        this.decisionRepository = decisionRepository;
        this.feedbackRepository = feedbackRepository;
        this.mlClient = mlClient;
        this.auditService = auditService;
        this.appUserRepository = appUserRepository;
    }

    @PostMapping
    public DecisionResponse submit(@Valid @RequestBody ApplicationSubmitRequest req, Authentication auth) {
        return decisionService.submitAndScore(req, auth.getName());
    }

    @GetMapping
    public List<ApplicationSummary> list(@RequestParam(defaultValue = "ALL")
                                          @Pattern(regexp = "ALL|APPROVE|STEP_UP|REVIEW|DECLINE") String action,
                                          @RequestParam(defaultValue = "100") @Min(1) @Max(500) int limit) {
        return queryService.listQueue(action, limit);
    }

    @GetMapping("/kpis")
    public Map<String, Object> kpis() {
        return queryService.kpis();
    }

    @GetMapping("/{id}")
    public Map<String, Object> detail(@PathVariable UUID id) {
        Application app = applicationRepository.findById(id)
                .orElseThrow(() -> new NoSuchElementException("application not found: " + id));
        var decision = decisionRepository.findFirstByApplicationIdOrderByCreatedAtDesc(id).orElse(null);
        return Map.of("application", app, "decision", decision == null ? Map.of() : decision);
    }

    @PostMapping("/{id}/narrative")
    public Map<String, Object> narrative(@PathVariable UUID id) {
        return mlClient.narrative(id.toString());
    }

    @GetMapping("/{id}/ring")
    public Map<String, Object> ring(@PathVariable UUID id) {
        return mlClient.getRing(id.toString());
    }

    @PostMapping("/{id}/feedback")
    public AnalystFeedback feedback(@PathVariable UUID id, @Valid @RequestBody FeedbackRequest req, Authentication auth) {
        var decision = decisionRepository.findFirstByApplicationIdOrderByCreatedAtDesc(id)
                .orElseThrow(() -> new NoSuchElementException("no decision on file for application: " + id));

        AnalystFeedback fb = new AnalystFeedback();
        fb.setApplicationId(id);
        fb.setVerdict(req.verdict());
        fb.setOriginalAction(decision.getAction());
        // Null for rules-only (degraded) decisions: there was no model score to record.
        fb.setOriginalScore(decision.getRiskScore());
        fb.setAnalystId(appUserRepository.findByUsername(auth.getName()).map(AppUser::getId).orElse(null));
        fb.setWasFalsePositive("LEGIT".equals(req.verdict()) &&
                ("DECLINE".equals(decision.getAction()) || "REVIEW".equals(decision.getAction())));
        fb.setNote(req.note());
        fb = feedbackRepository.save(fb);

        auditService.log(auth.getName(), "ANALYST_FEEDBACK", "application", id.toString(), "verdict=" + req.verdict());
        return fb;
    }
}
