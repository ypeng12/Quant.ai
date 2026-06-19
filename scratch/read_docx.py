import zipfile
import xml.etree.ElementTree as ET
import sys

def read_docx(file_path):
    try:
        namespaces = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        text_content = []
        with zipfile.ZipFile(file_path) as docx:
            tree = ET.parse(docx.open('word/document.xml'))
            root = tree.getroot()
            for elem in root.iter():
                # w:t contains the actual text strings
                if elem.tag.endswith('t'):
                    if elem.text:
                        text_content.append(elem.text)
                # w:p represents paragraphs, we add newline for spacing
                elif elem.tag.endswith('p'):
                    text_content.append('\n')
        
        # Combine text and clean up excess whitespace
        full_text = "".join(text_content)
        with open(r"c:\Users\pengy\OneDrive\Desktop\Quont\scratch\docx_content.md", "w", encoding="utf-8") as f:
            f.write(full_text)
        print("Success! Output written to docx_content.md")
    except Exception as e:
        print(f"Error reading docx: {str(e)}", file=sys.stderr)

if __name__ == '__main__':
    file_path = r"c:\Users\pengy\OneDrive\Desktop\Quont\QuontAI_Development_Plan_CN.docx"
    read_docx(file_path)
