// Intentional seed: does not escape CSV fields.
import {readFileSync} from "node:fs";
type Row = {id: string; name: string};
const rows: Row[] = JSON.parse(readFileSync(0, "utf8"));
process.stdout.write("id,name\n" + rows.map(r => `${r.id},${r.name}\n`).join(""));
