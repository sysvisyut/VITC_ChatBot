import fitz
import os
import camelot
import pandas as pd
from langchain_text_splitters import RecursiveCharacterTextSplitter

# processing multiple PDFs from a directory
def process_pdfs_in_directory(directory_path):
    """
    Processes all PDF files, extracting tables and non-table text separately to avoid redundancy.
    It identifies table locations and blanks them out before extracting the remaining page text.
    """
    all_data_objects = []
    
    if not os.path.isdir(directory_path):
        print(f"Error: Directory '{directory_path}' not found.")
        return []

    for filename in os.listdir(directory_path):
        if filename.lower().endswith(".pdf"):
            file_path = os.path.join(directory_path, filename)
            print(f"\n--- Processing file: {filename} ---")
            
            try:
                # --- Step 1: Extract Tables with Camelot and get their locations ---
                # CORRECTED: Using 'lattice' as it's more accurate for tables with clear grid lines.
                tables = camelot.read_pdf(file_path, pages='all', flavor='lattice')
                
                # Create a dictionary to hold the bounding box of tables on each page
                table_locations = {}

                print(f"Found {tables.n} tables. Converting to Markdown and logging locations.")
                for table in tables:
                    # Store table's bounding box to exclude its text later
                    if table.page not in table_locations:
                        table_locations[table.page] = []
                    
                    # The _bbox attribute gives the table coordinates (x1, y1, x2, y2)
                    table_locations[table.page].append(table._bbox)

                    # Convert table to Markdown in chunks to avoid massive single strings
                    df = table.df
                    df = df.replace(r'\n', ' ', regex=True)
                    if not df.empty:
                        # Set the first row as the header, ensuring column names are strings
                        df.columns = [str(col) for col in df.iloc[0]]
                        df = df[1:]
                        
                        # Chunk the dataframe into smaller pieces (e.g., 15 rows max) to prevent embedding truncation
                        chunk_size_rows = 15
                        for i in range(0, len(df), chunk_size_rows):
                            df_chunk = df.iloc[i:i + chunk_size_rows]
                            markdown_table = df_chunk.to_markdown(index=False)
                            table_object = {
                                "text_chunk": f"[Page {table.page}] The following table is found:\n\n{markdown_table}",
                                "source_file": filename,
                                "page_number": int(table.page)
                            }
                            all_data_objects.append(table_object)

                # --- Step 2: Extract non-table text using PyMuPDF, avoiding table areas ---
                doc = fitz.open(file_path)
                for page_num, page in enumerate(doc, 1): # Page numbers in fitz are 0-indexed, camelot is 1-indexed
                    bboxes_on_page = table_locations.get(page_num, [])
                    
                    # For each table on the page, add a redaction to "blank it out"
                    for bbox in bboxes_on_page:
                        page.add_redact_annot(fitz.Rect(bbox), fill=(1, 1, 1)) # Fill with white color
                    
                    # Apply the redactions, which effectively removes the text in those areas
                    page.apply_redactions()
                    
                    # Now, extract the text from the page. The table text is gone.
                    text = page.get_text()
                    # Add the remaining text as chunks if it's substantial
                    if len(text.strip().split()) > 15: # Heuristic to avoid very small/empty text chunks
                        splitter = RecursiveCharacterTextSplitter(
                            chunk_size=512, chunk_overlap=64,
                            separators=["\n\n", "\n", ".", " "]
                        )
                        chunks = splitter.split_text(text)
                        for chunk in chunks:
                            if not chunk.strip():
                                continue
                            text_object = {
                                "text_chunk": f"[Page {page_num}] {chunk.strip()}",
                                "source_file": filename,
                                "page_number": page_num
                            }
                            all_data_objects.append(text_object)
                doc.close()

            except Exception as e:
                print(f"❌ Error processing {filename}: {e}")
                
    print(f"\n✅ Total data chunks processed from all files: {len(all_data_objects)}")
    return all_data_objects

