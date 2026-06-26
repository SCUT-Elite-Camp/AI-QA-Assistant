package com.htc.bff.service;

import com.htc.bff.dto.ChatRequest;
import com.htc.bff.dto.ChatResponse;
import com.htc.bff.dto.Citation;
import java.util.List;
import java.util.UUID;
import org.springframework.stereotype.Service;

@Service
public class ChatService {
  private static final String Q1_ANSWER = "项目 Q1 阶段的核心目标是完成 AI 智能问答助手的最小可用闭环。"
      + "Web 层需要支持用户输入问题、调用后端 BFF 接口、展示助手回答、展示引用来源，"
      + "并在异常情况下给出友好的错误提示。当前阶段重点不是完整 Agent 能力，"
      + "而是先跑通从前端到 BFF，再到 Mock Agent 响应的端到端链路。";

  private static final String DEFAULT_ANSWER = "这是 Spring Boot BFF 返回的 Mock 答案。"
      + "当前接口用于前端联调，后续会在 BFF 中适配真实 Agent 响应。";

  public ChatResponse chat(ChatRequest request) {
    return new ChatResponse(
        UUID.randomUUID().toString(),
        "success",
        chooseAnswer(request.query()),
        List.of(new Citation(
            "HTC Q1 MVP Requirement",
            "https://example.com/htc/q1",
            "Q1 阶段目标是完成问答链路 MVP，包括输入、回答展示、引用来源和异常提示。"
        ))
    );
  }

  private String chooseAnswer(String query) {
    if (query.contains("Q1")
        || query.contains("第一阶段")
        || query.contains("项目 Q1 阶段需要完成哪些功能")) {
      return Q1_ANSWER;
    }

    return DEFAULT_ANSWER;
  }
}
