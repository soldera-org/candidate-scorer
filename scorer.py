import os
import pandas as pd
import PyPDF2
from anthropic import Anthropic
import json
from typing import List, Dict
import logging
import time

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class ProjectContext:
    def __init__(self, project_folder: str):
        """Initialize project context handler."""
        self.project_folder = project_folder
        self.context = None

    def read_pdf(self, file_path: str) -> str:
        """Read and extract text from a PDF file."""
        try:
            with open(file_path, "rb") as file:
                pdf_reader = PyPDF2.PdfReader(file)
                text = ""
                for page in pdf_reader.pages:
                    text += page.extract_text() + "\n"
                return text
        except Exception as e:
            logger.error(f"Error reading PDF {file_path}: {str(e)}")
            return ""

    def load_context(self) -> str:
        """Load and combine all project-related PDFs into a single context string."""
        if self.context is None:
            context = []
            if os.path.exists(self.project_folder):
                for filename in os.listdir(self.project_folder):
                    if filename.lower().endswith(".pdf"):
                        file_path = os.path.join(self.project_folder, filename)
                        pdf_text = self.read_pdf(file_path)
                        context.append(f"Content from {filename}:\n{pdf_text}")

            self.context = "\n\n".join(context) if context else ""
            logger.info(f"Loaded project context from {self.project_folder}")
        return self.context


class CandidateScorer:
    def __init__(self, api_key: str, project_context: ProjectContext):
        """Initialize the CandidateScorer."""
        self.anthropic = Anthropic(api_key=api_key)
        self.project_context = project_context

    def read_pdf(self, file_path: str) -> str:
        """Read and extract text from a PDF file."""
        try:
            with open(file_path, "rb") as file:
                pdf_reader = PyPDF2.PdfReader(file)
                text = ""
                for page in pdf_reader.pages:
                    text += page.extract_text() + "\n"
                return text
        except Exception as e:
            logger.error(f"Error reading PDF {file_path}: {str(e)}")
            return ""

    def evaluate_candidate(
        self, name: str, resume_text: str, experiences: str, screening_answers: str
    ) -> dict:
        """Evaluate a candidate using Claude API."""
        position_context = self.project_context.load_context()

        # Define default result in case of errors
        default_result = {
            "technical_skills": 0.0,
            "experience_relevance": 0.0,
            "cultural_fit": 0.0,
            "domain_knowledge": 0.0,
            "overall_score": 0.0,
            "domain_knowledge_notes": "Error processing response",
            "technical_notes": "Error processing response",
            "experience_notes": "Error processing response",
            "cultural_notes": "Error processing response",
            "overall_explanation": "Error processing response",
        }

        prompt = f"""Return ONLY a single JSON object formatted exactly like this example (replace with actual evaluations):

{{
  "technical_skills": 7.5,
  "experience_relevance": 8.0,
  "cultural_fit": 7.5,
  "Domain knowledge": 8.0,
  "overall_score": 7.8,
  "domain_knowledge_notes": "Demonstrates strong...",
  "technical_notes": "Strong background in...",
  "experience_notes": "Relevant experience in...",
  "cultural_notes": "Shows alignment with...",
  "overall_explanation": "Overall assessment shows..."
}}

Position Information:
{position_context}

Candidate Information:
Name: {name}
Experience: {experiences}
Screening Answers: {screening_answers}
Resume: {resume_text}

Evaluate based on:
1. Domain knowledge: How well do they know the industry (score 1-10).
2. Technical skills: qualifications and technical experience (score 1-10)
3. Experience relevance: how well past roles align with position (score 1-10)
4. Cultural fit: values alignment and team fit (score 1-10)

When conducting the evaluation, consider each company and position they have worked in carefully. If you don't have information about a company, look it up on the web. Make sure to consider the companies they have worked in - are these actually energy companies in Nordics? Put little emphasis on the questions they answered, as people are not very honest in answering these questions.

Provide detailed notes for each area and an overall explanation.
YOUR RESPONSE MUST BE ONLY THE JSON OBJECT."""

        try:
            response = self.anthropic.messages.create(
                model="claude-3-opus-20240229",
                max_tokens=1000,
                temperature=0.1,
                system="You are an expert technical recruiter. Respond ONLY with a valid JSON object.",
                messages=[{"role": "user", "content": prompt}],
            )

            # Log the raw response for debugging
            logger.debug(f"Raw response for {name}: {response.content}")

            # Parse the response
            if hasattr(response.content, "text"):
                # If it's a TextBlock object
                content = response.content.text
            elif isinstance(response.content, list):
                # If it's a list of TextBlocks
                content = response.content[0].text
            else:
                # If it's already a string
                content = str(response.content)

            try:
                # Try direct JSON parsing
                result = json.loads(content)
                logger.info(f"Successfully parsed response for {name}")
                return result
            except json.JSONDecodeError:
                # If direct parsing fails, try to extract JSON
                import re

                json_match = re.search(r"\{.*\}", content, re.DOTALL)
                if json_match:
                    json_str = json_match.group()
                    result = json.loads(json_str)
                    return result
                else:
                    logger.error(f"No valid JSON found in response for {name}")
                    return default_result

        except Exception as e:
            logger.error(f"Error evaluating candidate {name}: {str(e)}")
            if "rate_limit" in str(e).lower():
                logger.info("Rate limited. Waiting 30 seconds...")
                time.sleep(30)
                try:
                    # Retry once after rate limit
                    return self.evaluate_candidate(
                        name, resume_text, experiences, screening_answers
                    )
                except Exception as retry_e:
                    logger.error(f"Retry failed for {name}: {retry_e}")
            return default_result

    def process_candidates(self, input_csv: str, output_csv: str):
        """Process all candidates from input CSV and create output CSV with scores."""
        try:
            # Read input CSV
            df = pd.read_csv(input_csv)
            total_candidates = len(df)
            failed_candidates = []
            logger.info(f"Starting to process {total_candidates} candidates")

            # Initialize new columns
            df["Domain_Knowledge_Score"] = 0.0
            df["Technical_Skills_Score"] = 0.0
            df["Experience_Score"] = 0.0
            df["Cultural_Fit_Score"] = 0.0
            df["Overall_Score"] = 0.0
            df["Domain_Knowledge_Notes"] = ""
            df["Technical_Notes"] = ""
            df["Experience_Notes"] = ""
            df["Cultural_Notes"] = ""
            df["Overall_Explanation"] = ""
            df["Processing_Status"] = "Not Processed"  # Add status column

            # Process each candidate
            for index, row in df.iterrows():
                current_candidate = index + 1
                candidate_name = str(row["Name"])

                try:
                    logger.info(
                        f"Processing candidate {current_candidate}/{total_candidates}: {candidate_name}"
                    )

                    # Handle missing or NaN ResumeFile
                    resume_text = ""
                    try:
                        if pd.notna(row.get("ResumeFile")):
                            resume_path = os.path.join(
                                "candidates", str(row["ResumeFile"])
                            )
                            if os.path.exists(resume_path):
                                resume_text = self.read_pdf(resume_path)
                            else:
                                logger.warning(
                                    f"Resume file not found for {candidate_name}"
                                )
                    except Exception as e:
                        logger.error(
                            f"Error reading resume for {candidate_name}: {str(e)}"
                        )

                    # Evaluate candidate
                    result = self.evaluate_candidate(
                        candidate_name,
                        resume_text,
                        str(row.get("Experiences", "")),
                        str(row.get("Screening", "")),
                    )

                    # Update DataFrame with scores
                    df.at[index, "Domain_Knowledge_Score"] = float(
                        result.get("domain_knowledge", 0.0)
                    )
                    df.at[index, "Technical_Skills_Score"] = float(
                        result.get("technical_skills", 0.0)
                    )
                    df.at[index, "Experience_Score"] = float(
                        result.get("experience_relevance", 0.0)
                    )
                    df.at[index, "Cultural_Fit_Score"] = float(
                        result.get("cultural_fit", 0.0)
                    )
                    df.at[index, "Overall_Score"] = float(
                        result.get("overall_score", 0.0)
                    )
                    df.at[index, "Domain_Knowledge_Notes"] = str(
                        result.get("domain_knowledge_notes", "")
                    )
                    df.at[index, "Technical_Notes"] = str(
                        result.get("technical_notes", "")
                    )
                    df.at[index, "Experience_Notes"] = str(
                        result.get("experience_notes", "")
                    )
                    df.at[index, "Cultural_Notes"] = str(
                        result.get("cultural_notes", "")
                    )
                    df.at[index, "Overall_Explanation"] = str(
                        result.get("overall_explanation", "")
                    )
                    df.at[index, "Processing_Status"] = "Success"

                    logger.info(
                        f"Scored candidate {current_candidate}/{total_candidates}: {result.get('overall_score', 0.0)}"
                    )

                except Exception as e:
                    error_msg = (
                        f"Failed to process candidate {candidate_name}: {str(e)}"
                    )
                    logger.error(error_msg)
                    failed_candidates.append((candidate_name, str(e)))
                    df.at[index, "Processing_Status"] = f"Failed: {str(e)}"
                    continue

                finally:
                    # Save progress after each candidate
                    df.to_csv(output_csv, index=False)

                    # Add a delay between candidates to avoid rate limits
                    if current_candidate < total_candidates:
                        logger.info(
                            f"Waiting 5 seconds before next candidate... ({current_candidate}/{total_candidates} completed)"
                        )
                        time.sleep(5)

            # Sort by score descending, keeping failed candidates at the bottom
            df = df.sort_values(
                ["Processing_Status", "Overall_Score"], ascending=[True, False]
            )

            # Final save
            df.to_csv(output_csv, index=False)

            # Log summary
            successful = total_candidates - len(failed_candidates)
            logger.info(f"\nProcessing Summary:")
            logger.info(
                f"Successfully processed: {successful}/{total_candidates} candidates"
            )
            if failed_candidates:
                logger.info(f"Failed to process {len(failed_candidates)} candidates:")
                for name, error in failed_candidates:
                    logger.info(f"- {name}: {error}")
            logger.info(f"Results saved to {output_csv}")

        except Exception as e:
            logger.error(f"Critical error in processing: {str(e)}")
            # Save whatever we have processed so far
            df.to_csv(output_csv, index=False)
            logger.info(f"Partial results saved to {output_csv}")
            raise


def main():
    # Configuration
    API_KEY = "API_KEY"
    PROJECT_FOLDER = (
        "project_context"  # Folder containing job description, culture docs, etc.
    )
    INPUT_CSV = "candidates/candidates.csv"
    OUTPUT_CSV = "candidates/candidates_scored.csv"

    # Create project context and scorer
    project_context = ProjectContext(PROJECT_FOLDER)
    scorer = CandidateScorer(API_KEY, project_context)

    # Process candidates
    scorer.process_candidates(INPUT_CSV, OUTPUT_CSV)


if __name__ == "__main__":
    main()
