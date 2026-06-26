package com.htc.bff.controller;

import com.htc.bff.dto.ChatRequest;
import com.htc.bff.dto.ChatResponse;
import com.htc.bff.service.ChatService;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class ChatController {
  private final ChatService chatService;

  public ChatController(ChatService chatService) {
    this.chatService = chatService;
  }

  @PostMapping("/api/v1/chat")
  public ChatResponse chat(@Valid @RequestBody ChatRequest request) {
    return chatService.chat(request);
  }
}
