package com.htc.bff.dto;

import java.util.List;

public record ChatResponse(
    String trace_id,
    String status,
    String answer,
    List<Citation> citations
) {
}
