"""Bounded table evidence with explicit headers, row ranges and source geometry."""
from models.document import Chunk
from .budget import count_tokens, split_budget, token_limit


def table_chunks(block, doc_id, block_index, section_path, start_index, context_blocks=()):
    table = block.table
    headers = table.legacy_headers() if table else list(block.headers)
    rows = table.body_rows() if table else list(block.rows)
    row_offset = table.header_row_count if table else 0
    caption = table.caption if table else ''
    table_id = table.table_id if table else (block.block_id or f'{doc_id}-table-{block_index}')
    preamble = []
    inferred_header = False
    # Some exports put a merged title and instruction above the actual header.
    # Keep those as table context rather than repeating them as every column name.
    if not headers or len(set(x for x in headers if x)) <= 1:
        for i, row in enumerate(rows[:8]):
            values = [str(v).strip() for v in row if str(v).strip()]
            if len(set(values)) >= 2 and any(v.replace('.', '', 1).isdigit() for v in values):
                # Once numeric data starts, a later prose/status row is not a
                # header. Keep unnamed columns instead of inventing roles.
                break
            if len(set(values)) >= 2 and all(not v.replace('.', '', 1).isdigit() for v in values):
                headers, preamble = list(row), rows[:i]
                rows, row_offset = rows[i + 1:], row_offset + i + 1
                inferred_header = True
                break
    prefix = '\n'.join(filter(None, [caption, *[cb.to_markdown() for _, cb in context_blocks],
                                     *[' | '.join(dict.fromkeys(r)) for r in preamble]]))
    def escape(value):
        return str(value).replace('|', '\\|').replace('\n', '<br>')
    def render(group):
        width = max([len(headers), *(len(row) for _, row in group)], default=1)
        names = headers or [f'Column {i+1}' for i in range(width)]
        heading = '| ' + ' | '.join(escape(x) for x in names) + ' |'
        separator = '| ' + ' | '.join(['---'] * width) + ' |'
        body = ['| ' + ' | '.join(escape(v) for v in row) + ' |' for _, row in group]
        return '\n'.join(filter(None, [prefix, heading, separator, *body]))
    def facts(group):
        return '\n'.join(filter(None, [prefix, *[
            ' | '.join(f'{headers[i] if i < len(headers) and headers[i] else f"Column {i+1}"}: {v}'
                       for i, v in enumerate(row) if str(v).strip()) for _, row in group]]))
    groups, current = [], []
    for row_number, row in enumerate(rows, row_offset):
        if not any(str(v).strip() for v in row):
            continue
        proposed = current + [(row_number, row)]
        if current and max(count_tokens(render(proposed)), count_tokens(facts(proposed))) > token_limit():
            groups.append(current)
            current = []
        current.append((row_number, row))
    if current:
        groups.append(current)
    result = []
    for group in groups:
        display = render(group)
        semantic = facts(group)
        # An exceptionally wide row remains lossless. Its column labels and row
        # key are repeated for each field so splitting cannot move a value's owner.
        if max(count_tokens(display), count_tokens(semantic)) > token_limit():
            pieces = []
            for row_number, row in group:
                key = str(row[0]) if row else ''
                context = f'{prefix}\nRow {row_number + 1} ({key})\n'
                if count_tokens(context) >= token_limit() // 2:
                    context = f'Row {row_number + 1}\n'
                pending = []
                for i, value in enumerate(row):
                    if not str(value).strip():
                        continue
                    label = headers[i] if i < len(headers) and headers[i] else f'Column {i+1}'
                    field_prefix = f'{label}: '
                    for part in split_budget(str(value), max(16, token_limit()-count_tokens(context+field_prefix)-8)):
                        field = field_prefix + part
                        proposed = context + '\n'.join([*pending, field])
                        if pending and count_tokens(proposed) > token_limit():
                            text = context + '\n'.join(pending)
                            pieces.append((text, text, row_number, row_number))
                            pending = []
                        pending.append(field)
                if pending:
                    text = context + '\n'.join(pending)
                    pieces.append((text, text, row_number, row_number))
        else:
            pieces = [(display, semantic, group[0][0], group[-1][0])]
        for text, index_text, first, last in pieces:
            index = start_index + len(result)
            from .chunker import _page_regions
            regions = [*(table.page_regions if table else _page_regions([block])),
                       *_page_regions([cb for _, cb in context_blocks])]
            result.append(Chunk(index=index, chunk_id=f'{doc_id}_chunk_{index}', text=text,
                markdown_text=text, index_text=index_text, chunk_type='table', table_id=table_id,
                section_path=list(section_path),
                block_start=min([block_index, *[i for i, _ in context_blocks]]),
                block_end=max([block_index, *[i for i, _ in context_blocks]]),
                block_id=block.block_id, page_number=block.page_number, bbox=block.bbox,
                source='table', page_regions=regions,
                metadata={'row_start': first, 'row_end': last, 'headers': headers,
                          'header_inferred': inferred_header,
                          'context_block_ids': [cb.block_id for _, cb in context_blocks if cb.block_id],
                          'block_ids': [block.block_id] if block.block_id else []}))
    return result
