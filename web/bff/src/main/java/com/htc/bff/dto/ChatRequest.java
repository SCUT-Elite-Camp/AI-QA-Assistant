package com.htc.bff.dto;

import jakarta.validation.constraints.NotBlank;

public record ChatRequest(
    @NotBlank String query,
    String session_id,
    Boolean stream
) {
}
