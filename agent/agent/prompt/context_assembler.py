from agent.schemas.retrieval import RetrievalResult


class ContextAssembler:
    def assemble(self, retrieval_results: list[RetrievalResult]) -> str:
        blocks = []
        for index, result in enumerate(retrieval_results, start=1):
            blocks.append(
                "\n".join(
                    [
                        f"[{index}]",
                        f"title: {result.title}",
                        f"doc_id: {result.doc_id}",
                        f"chunk_id: {result.chunk_id}",
                        f"chunk_text: {result.chunk_text}",
                    ]
                )
            )
        return "\n\n".join(blocks)

