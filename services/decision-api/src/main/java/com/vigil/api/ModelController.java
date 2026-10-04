package com.vigil.api;

import com.vigil.domain.ModelRegistry;
import com.vigil.repo.ModelRegistryRepository;
import com.vigil.service.AuditService;
import com.vigil.service.MlClient;
import org.springframework.http.HttpStatus;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/v1/models")
public class ModelController {

    private final ModelRegistryRepository repo;
    private final MlClient mlClient;
    private final AuditService auditService;

    public ModelController(ModelRegistryRepository repo, MlClient mlClient, AuditService auditService) {
        this.repo = repo;
        this.mlClient = mlClient;
        this.auditService = auditService;
    }

    @GetMapping
    public List<ModelRegistry> list() {
        return repo.findAllByOrderByTrainedAtDesc();
    }

    @GetMapping("/cost-curve")
    public Map<String, Object> costCurve() {
        return mlClient.getCostCurve();
    }

    /**
     * Self-learning, exposed as an explicit admin action -- never automatic.
     * ml-service rebuilds the model from the dataset plus analyst feedback
     * and only hot-swaps if the new holdout PR-AUC is at least as good as
     * the incumbent's; see ml-service app/main.py::retrain for the gate.
     */
    @PostMapping("/retrain")
    @PreAuthorize("hasRole('ADMIN')")
    public Map<String, Object> retrain(Authentication auth) {
        Map<String, Object> result = mlClient.retrain();
        if (result == null || !result.containsKey("version") || !result.containsKey("promoted")) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "ml-service returned an unexpected retrain response");
        }
        auditService.log(auth.getName(), "RETRAIN", "model", String.valueOf(result.get("version")),
                "promoted=" + result.get("promoted") + " pr_auc=" + result.get("pr_auc"));
        return result;
    }
}
