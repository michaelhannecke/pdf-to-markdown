#!/usr/bin/env python3
"""
PDF to Markdown Converter

This script converts PDF documents to Markdown format using PyMuPDF for PDF extraction
and Gemma3:4b (via Ollama) for text processing and formatting.

Requirements:
- PyMuPDF (fitz)
- ollama
- requests
- argparse
"""

import argparse
import fitz  # PyMuPDF
import os
import re
import requests
import json
import time
from typing import List, Dict, Tuple, Optional


class PDFToMarkdownConverter:
    def __init__(self, ollama_url: str = "http://localhost:11434"):
        """
        Initialize the PDF to Markdown converter.

        Args:
            ollama_url: URL for the Ollama API (default: http://localhost:11434)
        """
        self.ollama_url = ollama_url
        self.model = "gemma3:4b"

    def extract_text_from_pdf(self, pdf_path: str) -> List[Dict]:
        """
        Extract text and structure from a PDF document.

        Args:
            pdf_path: Path to the PDF file

        Returns:
            List of dictionaries containing page number, text content, and any structural information
        """
        document = fitz.open(pdf_path)
        pages = []

        for page_num, page in enumerate(document):
            # Extract text
            text = page.get_text("text")

            # Get page dimensions
            width, height = page.rect.width, page.rect.height

            # Extract images (optional - for future enhancement)
            # images = self._extract_images(page)

            # Extract blocks (paragraphs, headings, etc.)
            blocks = page.get_text("blocks")
            structured_blocks = []

            for block in blocks:
                x0, y0, x1, y1, text, block_num, block_type = block
                structured_blocks.append(
                    {"text": text.strip(), "bbox": (x0, y0, x1, y1), "type": block_type}
                )

            pages.append(
                {
                    "page_num": page_num + 1,
                    "text": text,
                    "width": width,
                    "height": height,
                    "blocks": structured_blocks,
                }
            )

        document.close()
        return pages

    def process_with_gemma(self, content: str, instruction: str) -> str:
        """
        Process text content with Gemma3:12b model via Ollama.

        Args:
            content: The text content to process
            instruction: The instruction for Gemma to follow

        Returns:
            Processed markdown text
        """
        prompt = f"""
        Instruction: {instruction}
        Content: {content}

        Please process this text content into well-formatted Markdown."""

        response = requests.post(
            f"{self.ollama_url}/api/generate",
            json={"model": self.model, "prompt": prompt, "stream": False},
        )

        if response.status_code == 200:
            return response.json().get("response", "")
        else:
            raise Exception(f"Error processing with Gemma: {response.text}")

    def _chunk_text(self, text: str, max_chunk_size: int = 8000) -> List[str]:
        """
        Split text into manageable chunks for the LLM.

        Args:
            text: Text to chunk
            max_chunk_size: Maximum chunk size in characters

        Returns:
            List of text chunks
        """
        # Try to split at paragraph boundaries
        paragraphs = text.split("\n\n")
        chunks = []
        current_chunk = ""

        for paragraph in paragraphs:
            if len(current_chunk) + len(paragraph) + 2 <= max_chunk_size:
                if current_chunk:
                    current_chunk += "\n\n"
                current_chunk += paragraph
            else:
                if current_chunk:
                    chunks.append(current_chunk)

                # If a single paragraph is too large, split it further
                if len(paragraph) > max_chunk_size:
                    sentences = re.split(r"(?<=[.!?])\s+", paragraph)
                    current_chunk = ""

                    for sentence in sentences:
                        if len(current_chunk) + len(sentence) + 1 <= max_chunk_size:
                            if current_chunk:
                                current_chunk += " "
                            current_chunk += sentence
                        else:
                            chunks.append(current_chunk)
                            current_chunk = sentence
                else:
                    current_chunk = paragraph

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def convert_to_markdown(
        self, pdf_path: str, output_path: Optional[str] = None
    ) -> str:
        """
        Convert a PDF document to Markdown.

        Args:
            pdf_path: Path to the PDF file
            output_path: Path to save the Markdown file (optional)

        Returns:
            The generated Markdown content
        """
        print(f"Extracting text from {pdf_path}...")
        pages = self.extract_text_from_pdf(pdf_path)

        full_content = ""
        for i, page in enumerate(pages):
            print(f"Processing page {i + 1}/{len(pages)}...")

            # Process page content with Gemma
            page_text = page["text"]

            # For longer pages, chunk the text
            if len(page_text) > 8000:
                chunks = self._chunk_text(page_text)
                processed_chunks = []

                for j, chunk in enumerate(chunks):
                    print(f"  Processing chunk {j + 1}/{len(chunks)}...")
                    instruction = f"""
                    Convert this text chunk from page {page["page_num"]} of a PDF document to well-formatted Markdown.
                    This is chunk {j + 1} of {len(chunks)} from this page.
                    Preserve headings, lists, tables, and other structural elements.
                    Do not add any explanatory text or commentary."""
                    processed_chunk = self.process_with_gemma(chunk, instruction)
                    processed_chunks.append(processed_chunk)

                # Final processing to combine chunks coherently
                combined_chunks = "\n\n".join(processed_chunks)
                instruction = f"""
                This content represents page {page["page_num"]} of a PDF document, split into chunks for processing.
                Please combine these chunks into a single coherent Markdown page, removing any redundancies or artifacts from the chunking process.
                Ensure proper heading hierarchy and structure."""

                processed_content = self.process_with_gemma(
                    combined_chunks, instruction
                )

            else:
                instruction = f"""
                Convert this text from page {page["page_num"]} of a PDF document to well-formatted Markdown.
                Preserve headings, lists, tables, and other structural elements.
                Identify and format headings appropriately based on font size and position.
                For lists, ensure proper Markdown list formatting.
                For tables, convert to Markdown table syntax.
                Do not add any explanatory text or commentary."""

                processed_content = self.process_with_gemma(page_text, instruction)

            full_content += processed_content + "\n\n"

        # Final pass to ensure consistent document structure
        final_instruction = """
        Review this full document and ensure:
        1. Consistent heading hierarchy throughout
        2. Proper formatting of lists, tables, and other elements
        3. Removal of any redundant or repeated content
        4. Sensible page transitions
        Preserve all content but enhance its Markdown formatting for readability."""

        print("Finalizing document structure...")
        if len(full_content) > 12000:
            # For very large documents, process in sections
            print("Document is large, processing in sections...")
            final_content = ""
            section_size = 10000  # Process 10k chars at a time, with some overlap
            overlap = 1000

            for i in range(0, len(full_content), section_size - overlap):
                section = full_content[i : i + section_size]
                section_instruction = f"""
                This is section {i // (section_size - overlap) + 1} of a larger document being converted to Markdown.
                {final_instruction}"""

                processed_section = self.process_with_gemma(
                    section, section_instruction
                )
                final_content += processed_section

            # Final pass to clean up section boundaries
            boundary_clean_instruction = """
            This document was processed in sections. Please clean up any artifacts or inconsistencies at section boundaries.
            Ensure heading hierarchy is consistent throughout the document. """
            final_markdown = self.process_with_gemma(
                final_content, boundary_clean_instruction
            )
        else:
            final_markdown = self.process_with_gemma(full_content, final_instruction)

        # Save to file if output path provided
        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(final_markdown)
            print(f"Markdown saved to {output_path}")

        return final_markdown


def main():
    parser = argparse.ArgumentParser(
        description="Convert PDF documents to Markdown using PyMuPDF and Gemma3:12b"
    )
    parser.add_argument("pdf_path", help="Path to the PDF file to convert")
    parser.add_argument(
        "--output",
        "-o",
        help="Path to save the output Markdown file (default: same name as PDF with .md extension)",
    )
    parser.add_argument(
        "--ollama-url",
        default="http://localhost:11434",
        help="URL for the Ollama API (default: http://localhost:11434)",
    )

    args = parser.parse_args()

    # Set default output path if not provided
    if not args.output:
        base_name = os.path.splitext(args.pdf_path)[0]
        args.output = f"{base_name}.md"

    converter = PDFToMarkdownConverter(ollama_url=args.ollama_url)
    converter.convert_to_markdown(args.pdf_path, args.output)
    print("Conversion complete!")


if __name__ == "__main__":
    main()
